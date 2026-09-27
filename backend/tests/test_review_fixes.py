"""Regressions for issues found in an independent review of the add-ons."""

import json
import os
import shutil
import subprocess

import pytest

from backend.ingest import geocode as geo
from backend.ingest.geocode import Match, Nominatim
from backend.ingest.watch import Watcher
from backend.weather.risk import build_window, overlap_weather

from .conftest import REPO_ROOT
from .test_weather import _flat_clim

node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _node(script: str, env=None) -> str:
    return subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True,
                          check=True, env={**os.environ, **(env or {})}).stdout


@node
def test_summary_text_matches_js_for_whole_numbers():
    clim = _flat_clim({m: 10 for m in range(1, 13)})  # every shared month = 10.0 days
    pa, pb = {"in_service_date": "6/1/2026"}, {"in_service_date": "12/31/2026"}
    py = overlap_weather(clim, clim, pa, pb)["summary"]
    js = _node(f"""
import {json.dumps(str(REPO_ROOT / "app" / "weather.js"))};
const W = globalThis.GridlockWeather;
process.stdout.write(W.overlapWeather({json.dumps(clim)}, {json.dumps(clim)}, {json.dumps(pa)}, {json.dumps(pb)}).summary);
""")
    assert js == py and "~60 weather-lost" in py


@node
def test_js_rejects_the_same_bad_dates_as_python():
    dates = ["13/01/2030", "2/30/2030", "0/1/2030", "2030-1-5", "2030-02-29", "2028-02-29",
             "6/1/2033", "2025-06-01", "12/31/2024", "", "TBD"]
    js = json.loads(_node(f"""
import {json.dumps(str(REPO_ROOT / "app" / "weather.js"))};
const W = globalThis.GridlockWeather;
process.stdout.write(JSON.stringify({json.dumps(dates)}.map(d => W.buildWindow(d))));
"""))
    py = [[list(ym) for ym in build_window(d)] for d in dates]
    assert js == py
    assert py[0] == [] and py[1] == [] and py[2] == [] and py[4] == []  # impossible dates
    assert py[3] and py[5]  # 1-digit ISO parts and a real leap day are fine


@node
def test_iso_dates_display_in_the_right_month_in_us_time_zones():
    out = _node(f"""
import {{ fmtDate }} from {json.dumps(str(REPO_ROOT / "frontend" / "src" / "lib" / "format.js"))};
process.stdout.write(JSON.stringify(["2025-06-01", "2025-05-01", "6/1/2033"].map(fmtDate)));
""", env={"TZ": "America/New_York"})
    assert json.loads(out) == ["Jun 2025", "May 2025", "Jun 2033"]
    # The static app carries the same fix.
    assert "new Date(+iso[1], +iso[2] - 1, +iso[3])" in (REPO_ROOT / "app" / "app.js").read_text()


def test_watcher_survives_bad_export_and_does_not_rerun_failed_pipeline(tmp_path):
    xlsx, pdf = tmp_path / "x.xlsx", tmp_path / "a.pdf"
    xlsx.write_bytes(b"not really a workbook")
    pdf.write_bytes(b"%PDF")
    runs = []

    def failing_pipeline():
        runs.append(1)
        raise RuntimeError("offline")

    def failing_export(*_a, **_k):
        raise ValueError("Excel is mid-save")

    w = Watcher(xlsx=xlsx, pdfs=[pdf], processed=tmp_path, state_file=tmp_path / "s.json",
                weather=False, log=lambda *_: None, run_pipeline=failing_pipeline, export=failing_export)
    assert w.tick() == ["xlsx-failed"]  # logged, not raised
    assert w.tick() == []  # not retried every tick

    st = pdf.stat()
    os.utime(pdf, (st.st_atime, st.st_mtime + 5))
    assert w.tick() == ["pdfs-failed"]
    assert w.tick() == [] and w.tick() == []
    assert runs == [1]  # one attempt per change


def test_nominatim_does_not_cache_network_failures(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("network down")

    monkeypatch.setattr(geo, "_http_json", boom)
    monkeypatch.setattr(geo.time, "sleep", lambda *_: None)
    n = Nominatim(cache=tmp_path / "n.json")
    assert n.search("Hooks substation, South Carolina") == []
    n.save()
    assert json.loads((tmp_path / "n.json").read_text()) == {}

    monkeypatch.setattr(geo, "_http_json", lambda *_a, **_k: [{"lat": "1", "lon": "2"}])
    assert n.search("Hooks substation, South Carolina") == [{"lat": "1", "lon": "2"}]


def test_half_located_project_is_low_confidence():
    from backend.ingest.pipeline import locate_project

    def geocode(name, state):
        if name == "Stevens Creek":
            return Match(query=name, lat=33.56, lon=-82.05, confidence="high", method="osm", score=1)
        return Match(query=name)

    rec = {"source_id": "6809 E", "utility": "Dominion Energy South Carolina", "state": "SC",
           "project_name": "Stevens Creek - Hooks 115kV/LR Plumb Branch 46kV Rebuilds",
           "in_service_date": "2024-12-31"}
    p = locate_project(rec, geocode)
    assert (p["lat_center"], p["location_confidence"]) == (33.56, "low")
    assert p["project_id"] == "DESC-6809E" and p["name_b"] == "Hooks" and p["lat_b"] is None


def test_nominatim_gives_up_fast_on_repeated_or_certificate_failures(tmp_path, monkeypatch):
    """A Mac without Python's certificates must not crawl through hundreds of
    1-second-spaced doomed requests (seen in a real first run)."""
    import ssl
    import urllib.error

    monkeypatch.setattr(geo.time, "sleep", lambda *_: None)
    calls = []

    def cert_fail(*_a, **_k):
        calls.append(1)
        raise urllib.error.URLError(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED"))

    monkeypatch.setattr(geo, "_http_json", cert_fail)
    n = Nominatim(cache=tmp_path / "n.json", log=lambda *_: None)
    for i in range(50):
        n.search(f"q{i}")
    assert len(calls) == 1 and "Install Certificates" in n.disabled_reason

    calls.clear()
    monkeypatch.setattr(geo, "_http_json", lambda *_a, **_k: calls.append(1) or (_ for _ in ()).throw(OSError("down")))
    n = Nominatim(cache=tmp_path / "n2.json", log=lambda *_: None)
    for i in range(50):
        n.search(f"q{i}")
    assert len(calls) == Nominatim.MAX_CONSECUTIVE_FAILURES


def test_weather_fetch_explains_certificate_errors(monkeypatch):
    import ssl
    import urllib.error

    import backend.weather.fetch as fetch

    def cert_fail(*_a, **_k):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED"))

    monkeypatch.setattr(fetch, "get_json", cert_fail)
    monkeypatch.setattr(fetch.time, "sleep", lambda *_: pytest.fail("should not retry a cert error"))
    with pytest.raises(RuntimeError, match="Install Certificates"):
        fetch.fetch_daily(33.5, -82.0)
