"""Weather-risk add-on: climatology, build windows, overlap risk, API, and
Python <-> JavaScript parity (app/weather.js is what both UIs run)."""

import json
import math
import random
import shutil
import subprocess
from datetime import date, timedelta

import pytest

from backend.weather.climatology import classify_day, monthly_climatology, round_half_up
from backend.weather.fetch import archive_url, build_climatology_cache, grid_cell
from backend.weather.risk import build_window, overlap_weather, risk_level, window_risk

from .conftest import REPO_ROOT


def synthetic_daily(seed: int, start=date(2015, 1, 1), end=date(2024, 12, 31)) -> dict:
    """Deterministic, seasonal fake history in Open-Meteo's `daily` shape
    (hot stormy summers, windier winters, occasional missing values)."""
    rng = random.Random(seed)
    out = {k: [] for k in ["time", "precipitation_sum", "temperature_2m_max", "wind_gusts_10m_max", "weather_code"]}
    d = start
    while d <= end:
        season = math.sin((d.timetuple().tm_yday - 105) / 365 * 2 * math.pi)  # ~+1 mid-July
        out["time"].append(d.isoformat())
        out["precipitation_sum"].append(None if rng.random() < 0.01 else round(rng.expovariate(1 / (6 + 4 * season)), 1))
        out["temperature_2m_max"].append(round(24 + 10 * season + rng.gauss(0, 3), 1))
        out["wind_gusts_10m_max"].append(round(max(5.0, rng.gauss(34 - 6 * season, 10)), 1))
        out["weather_code"].append(95 if rng.random() < max(0.02, 0.25 * season) else rng.choice([0, 1, 3, 61, 63]))
        d += timedelta(days=1)
    return out


# ---------- climatology ----------

def test_classify_day_thresholds_are_inclusive():
    assert classify_day(25.0, 20, 10, 0)["heavy_rain"] is True
    assert classify_day(24.9, 34.9, 54.9, 94)["bad"] is False
    assert classify_day(None, 35.0, None, None) == {
        "heavy_rain": False, "heat": True, "wind": False, "storm": False, "bad": True,
    }
    assert classify_day(0, 20, 55, 0)["wind"] is True
    assert classify_day(0, 20, 10, 99)["storm"] is True


def test_monthly_climatology_counts_by_hand():
    daily = {
        "time": ["2020-07-01", "2020-07-02", "2021-07-01", "2021-07-02", "2020-01-01"],
        "precipitation_sum": [30, 0, 0, 0, 0],
        "temperature_2m_max": [30, 36, 30, 30, 10],
        "wind_gusts_10m_max": [10, 10, 60, 10, 10],
        "weather_code": [0, 0, 95, 0, 0],
    }
    clim = {r["month"]: r for r in monthly_climatology(daily)}
    jul = clim[7]
    # 2 years of July, 2 days each; bad days: 07-01 (rain), 07-02 (heat), 2021-07-01 (wind+storm)
    assert jul["days"] == 2.0
    assert jul["bad_days"] == 1.5
    assert jul["heavy_rain_days"] == 0.5 and jul["heat_days"] == 0.5
    assert jul["wind_days"] == 0.5 and jul["storm_days"] == 0.5
    assert jul["bad_share"] == 0.75
    assert clim[1]["bad_days"] == 0.0
    assert clim[3]["days"] == 0.0 and clim[3]["bad_share"] == 0.0  # no data, no crash


def test_round_half_up_matches_js_math_round():
    assert round_half_up(2.25, 1) == 2.3  # Python's round() would give 2.2
    assert round_half_up(0.1235, 3) == 0.124
    assert round_half_up(7.0, 1) == 7.0


# ---------- build windows & risk ----------

def test_build_window_formats():
    w = build_window("6/1/2033")
    assert len(w) == 12 and w[0] == (2032, 7) and w[-1] == (2033, 6)
    assert build_window("12/31/2024")[0] == (2024, 1)
    assert build_window("2025-06-01")[-1] == (2025, 6)
    assert build_window(None) == [] and build_window("TBD") == []


def test_risk_levels():
    assert risk_level(0.0) == "low" and risk_level(0.149) == "low"
    assert risk_level(0.15) == "moderate" and risk_level(0.299) == "moderate"
    assert risk_level(0.30) == "high"


def _flat_clim(bad_by_month: dict[int, float]) -> list[dict]:
    return [
        {"month": m, "days": 30.0, "heavy_rain_days": 0.0, "heat_days": bad_by_month.get(m, 0.0),
         "wind_days": 0.0, "storm_days": 0.0, "bad_days": bad_by_month.get(m, 0.0),
         "bad_share": round_half_up(bad_by_month.get(m, 0.0) / 30, 3)}
        for m in range(1, 13)
    ]


def test_window_risk_finds_best_stretch_and_high_months():
    clim = _flat_clim({6: 12, 7: 15, 8: 12, 11: 1, 12: 1, 1: 1, 2: 1})
    r = window_risk(clim, "12/31/2024")  # Jan..Dec 2024
    assert r["window"] == "Jan 2024 – Dec 2024"
    assert r["high_risk_months"] == ["Jun 2024", "Jul 2024", "Aug 2024"]
    assert r["worst_month"] == {"label": "Jul 2024", "bad_days": 15}
    # Mar-May are all 0 -> earliest zero-sum stretch wins
    assert r["best_stretch"] == {"start": "Mar 2024", "end": "May 2024", "bad_days": 0.0}
    assert r["expected_bad_days"] == 43.0
    assert r["dominant_hazard"] == "extreme heat"


def test_overlap_weather_shared_and_disjoint_windows():
    clim = _flat_clim({7: 12})
    pa = {"in_service_date": "6/1/2026"}
    pb = {"in_service_date": "12/31/2026"}  # windows share Jan..Jun 2026
    ow = overlap_weather(clim, clim, pa, pb)
    assert [r["label"] for r in ow["shared_months"]] == [
        "Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026",
    ]
    assert ow["summary"].startswith("Build windows overlap for 6 months")

    far = overlap_weather(clim, clim, {"in_service_date": "12/31/2024"}, {"in_service_date": "6/1/2033"})
    assert far["shared_months"] == [] and far["best_shared_stretch"] is None
    assert far["summary"].startswith("Build windows don't overlap in time")

    missing = overlap_weather(None, clim, pa, pb)
    assert missing["project_a"] is None and "unavailable" in missing["summary"]


# ---------- fetch (no network: fake fetcher) ----------

def test_cache_builder_dedupes_nearby_projects(projects):
    calls = []

    def fake_fetch(lat, lon):
        calls.append((lat, lon))
        return synthetic_daily(seed=int(abs(lat * 1000)) % 97)

    cache = build_climatology_cache(projects, fetch=fake_fetch, pause=0)
    located = [p for p in projects if p.get("lat_center") is not None]
    assert set(cache["projects"]) == {p["project_id"] for p in located}
    assert len(calls) == len({grid_cell(p["lat_center"], p["lon_center"]) for p in located})
    assert len(calls) < len(located)  # the 25 km grid shares requests
    assert all(len(v["monthly"]) == 12 for v in cache["projects"].values())
    assert cache["complete"] is True


def test_grid_cell_rounds_half_up():
    assert grid_cell(32.125, -81.375) == (32.25, -81.25)
    assert grid_cell(33.66, -82.2) == (33.75, -82.25)


def test_cache_resumes_after_rate_limit_and_saves_each_cell(tmp_path, projects):
    import backend.weather.fetch as fetch

    located = [p for p in projects if p.get("lat_center") is not None]
    n_cells = len({grid_cell(p["lat_center"], p["lon_center"]) for p in located})
    calls, saves = [], []

    def limited_after_two(lat, lon):
        if len(calls) == 2:
            raise fetch.RateLimited("daily allowance used up")
        calls.append((lat, lon))
        return synthetic_daily(seed=1)

    partial = build_climatology_cache(projects, fetch=limited_after_two, pause=0,
                                      save=lambda c: saves.append(len(c["projects"])))
    assert partial["complete"] is False and len(saves) == 2  # saved after each cell
    assert 0 < len(partial["projects"]) < len(located)

    # Next run starts from the partial cache and only fetches what's left.
    rest = []
    done = build_climatology_cache(projects, fetch=lambda la, lo: rest.append((la, lo)) or synthetic_daily(seed=1),
                                   pause=0, existing=partial)
    assert done["complete"] is True and set(done["projects"]) == {p["project_id"] for p in located}
    assert len(rest) == n_cells - 2 and not set(rest) & set(calls)


def test_fetch_daily_waits_out_429_then_gives_up_cleanly(monkeypatch):
    import urllib.error

    import backend.weather.fetch as fetch

    waits, attempts = [], []

    def always_429(*_a, **_k):
        attempts.append(1)
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)

    monkeypatch.setattr(fetch, "get_json", always_429)
    monkeypatch.setattr(fetch.time, "sleep", waits.append)
    with pytest.raises(fetch.RateLimited):
        fetch.fetch_daily(33.5, -82.0)
    assert len(attempts) == 3 and waits == [fetch.RATE_LIMIT_WAIT_S] * 2


def test_fetch_to_file_is_resumable_and_atomic(tmp_path, projects):
    import backend.weather.fetch as fetch

    out = tmp_path / "w.json"
    calls = []
    fake = lambda la, lo: calls.append(1) or synthetic_daily(seed=2)  # noqa: E731
    cache = fetch.fetch_to_file(projects, out, log=lambda *_: None, pause=0, fetch=fake)
    assert cache["complete"] and json.loads(out.read_text())["complete"]
    assert not (tmp_path / "w.json.tmp").exists()
    n = len(calls)
    fetch.fetch_to_file(projects, out, log=lambda *_: None, pause=0, fetch=fake)
    assert len(calls) == n  # complete cache: a re-run makes no requests


def test_archive_url_has_all_variables():
    url = archive_url(33.66, -82.2)
    for v in ["precipitation_sum", "temperature_2m_max", "wind_gusts_10m_max", "weather_code"]:
        assert v in url
    assert "start_date=2015-01-01" in url and "end_date=2024-12-31" in url


# ---------- Python <-> JavaScript parity ----------

@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_matches_python_on_every_flagged_overlap(tmp_path, projects, spreadsheet_overlaps):
    by_id = {p["project_id"]: p for p in projects}
    dailies = {p["project_id"]: synthetic_daily(seed=i) for i, p in enumerate(projects)}
    (tmp_path / "input.json").write_text(json.dumps({
        "dailies": dailies,
        "projects": by_id,
        "pairs": [[o["project_id_a"], o["project_id_b"]] for o in spreadsheet_overlaps],
    }))
    script = tmp_path / "run.js"
    script.write_text(f"""
require({json.dumps(str(REPO_ROOT / "app" / "weather.js"))});
const W = globalThis.GridlockWeather;
const inp = require({json.dumps(str(tmp_path / "input.json"))});
const clim = {{}};
for (const [id, d] of Object.entries(inp.dailies)) clim[id] = W.monthlyClimatology(d);
const overlaps = inp.pairs.map(([a, b]) =>
  W.overlapWeather(clim[a], clim[b], inp.projects[a], inp.projects[b]));
process.stdout.write(JSON.stringify({{ clim, overlaps }}));
""")
    js = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout)

    py_clim = {pid: monthly_climatology(d) for pid, d in dailies.items()}
    assert js["clim"] == py_clim

    py_overlaps = [
        overlap_weather(py_clim[a], py_clim[b], by_id[a], by_id[b])
        for a, b in [[o["project_id_a"], o["project_id_b"]] for o in spreadsheet_overlaps]
    ]
    assert js["overlaps"] == py_overlaps
    # Sanity: the synthetic seasons produce a mix of risk levels, so the parity
    # check actually exercises every branch of riskLevel().
    levels = {m["level"] for ow in py_overlaps for side in ("project_a", "project_b") for m in ow[side]["months"]}
    assert levels == {"low", "moderate", "high"}


# ---------- API ----------

def test_weather_endpoints(monkeypatch, tmp_path, projects):
    from fastapi.testclient import TestClient

    import backend.main as main

    cache = build_climatology_cache(projects, fetch=lambda lat, lon: synthetic_daily(seed=3), pause=0)
    cache_path = tmp_path / "weather_climatology.json"
    cache_path.write_text(json.dumps(cache))
    monkeypatch.setattr(main, "WEATHER_CACHE", cache_path)
    client = TestClient(main.app)

    r = client.get("/weather")
    assert r.status_code == 200 and set(r.json()["projects"]) == set(cache["projects"])

    r = client.get("/weather/overlap", params={"project_id_a": "DESC_2", "project_id_b": "GPC_1"})
    assert r.status_code == 200
    body = r.json()
    assert body["project_a"]["window"] == "Jan 2024 – Dec 2024"
    assert body["project_b"]["window"] == "Jul 2032 – Jun 2033"
    assert body["shared_months"] == []

    assert client.get("/weather/overlap", params={"project_id_a": "X", "project_id_b": "GPC_1"}).status_code == 404

    monkeypatch.setattr(main, "WEATHER_CACHE", tmp_path / "missing.json")
    assert client.get("/weather").status_code == 404


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_on_demand_weather_matches_python_grid(tmp_path, projects):
    """The browser fetches missing pairs live: it must use the same grid as
    the Python cache, reuse a cached neighbor in the same cell instead of
    re-fetching, and report a 429 as a rate limit."""
    located = [p for p in projects if p.get("lat_center") is not None]
    # Lead with a project that shares its grid cell with another one.
    cell_of = lambda p: grid_cell(p["lat_center"], p["lon_center"])  # noqa: E731
    shared = next(p for p in located if sum(cell_of(q) == cell_of(p) for q in located) > 1)
    located = [shared] + [p for p in located if p is not shared]
    script = tmp_path / "t.js"
    script.write_text(f"""
require({json.dumps(str(REPO_ROOT / "app" / "weather.js"))});
const W = globalThis.GridlockWeather;
const projects = {json.dumps(located)};
(async () => {{
  const cells = projects.map((p) => W.gridCell(p.lat_center, p.lon_center));
  const [first, ...rest] = projects;
  const [lat, lon] = W.gridCell(first.lat_center, first.lon_center);
  const clim = {{ [first.project_id]: {{ lat, lon, monthly: ["m"] }} }};
  const missing = W.missingProjects(clim, rest).map((p) => p.project_id);
  globalThis.fetch = async () => ({{ status: 429, ok: false }});
  let limited = false;
  try {{ await W.fetchClimatologyLive([first]); }} catch (e) {{ limited = !!e.rateLimited; }}
  console.log(JSON.stringify({{ cells, missing, filled: Object.keys(clim), limited }}));
}})();
""")
    out = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout)
    assert [tuple(c) for c in out["cells"]] == [grid_cell(p["lat_center"], p["lon_center"]) for p in located]

    first_cell = grid_cell(located[0]["lat_center"], located[0]["lon_center"])
    same = {p["project_id"] for p in located[1:] if grid_cell(p["lat_center"], p["lon_center"]) == first_cell}
    assert same, "fixture should have neighbors sharing a cell"
    assert set(out["filled"]) == {located[0]["project_id"]} | same  # neighbors reused, not re-fetched
    assert set(out["missing"]) == {p["project_id"] for p in located[1:]} - same
    assert out["limited"] is True
