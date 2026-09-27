"""Fetch 10 years of daily weather history per project and cache the climatology.

Source: Open-Meteo historical archive (ERA5 reanalysis) — free, no API key,
CORS-enabled. Standard library only, so this runs without any pip installs:

    python3 -m backend.weather.fetch            # writes data/processed/weather_climatology.json

Run it once while online and the weather panel works offline afterwards
(run-app.sh starts it in the background; the page fetches any pair it's
missing live, on click).

Rate limits — why this is paced: Open-Meteo's free tier allows 600 calls/min,
5,000/hour, 10,000/day, and counts every 2 weeks of data at one location as a
call. Ten years of daily data at one point is therefore ~260 calls: about two
locations a minute and ~38 a day. So we:
  * share one request per ~25 km grid cell (the resolution of the ERA5
    reanalysis behind the data, so no detail is lost),
  * space requests MIN_INTERVAL_S apart and back off on HTTP 429,
  * save after every cell, so a run cut short by the hourly/daily cap
    resumes where it stopped next time.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from backend.net import CERT_HELP, get_json, is_cert_error
from backend.weather.climatology import DAILY_VARIABLES, THRESHOLDS, monthly_climatology

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECTS = REPO_ROOT / "data" / "processed" / "projects.json"
DEFAULT_OUT = REPO_ROOT / "data" / "processed" / "weather_climatology.json"

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
PERIOD_START = "2015-01-01"
PERIOD_END = "2024-12-31"

GRID_DEG = 0.25  # ~25 km: ERA5's resolution; app/weather.js uses the same grid
MIN_INTERVAL_S = 30  # ~260 weighted calls per request vs 600/min
RATE_LIMIT_WAIT_S = 65  # one per-minute window, plus slack


class RateLimited(RuntimeError):
    """Open-Meteo said 429 even after waiting out a minute: the hourly or
    daily allowance is used up. Progress so far is kept; re-run later."""


def grid_cell(lat: float, lon: float) -> tuple[float, float]:
    """Snap to the GRID_DEG grid (round half up, matching JS Math.round)."""
    snap = lambda x: round(math.floor(x / GRID_DEG + 0.5) * GRID_DEG, 4)  # noqa: E731
    return snap(lat), snap(lon)


def archive_url(lat: float, lon: float, start: str = PERIOD_START, end: str = PERIOD_END) -> str:
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "start_date": start,
        "end_date": end,
        "daily": ",".join(DAILY_VARIABLES),
        "timezone": "America/New_York",
    }
    return f"{ARCHIVE_URL}?{urllib.parse.urlencode(params)}"


def fetch_daily(lat: float, lon: float, timeout: float = 60.0, retries: int = 2, log=lambda *_: None) -> dict:
    """Daily history for one point, as Open-Meteo's `daily` dict of parallel arrays.
    Waits out a per-minute 429 and retries; raises RateLimited if it persists."""
    url = archive_url(lat, lon)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            payload = get_json(url, timeout=timeout)
            if "daily" not in payload:
                raise RuntimeError(payload.get("reason", "Open-Meteo response had no 'daily' block"))
            return payload["daily"]
        except Exception as e:  # network errors, rate limits, bad payloads
            last_err = e
            if is_cert_error(e):  # retrying can't fix a missing certificate store
                raise RuntimeError(CERT_HELP) from e
            limited = isinstance(e, urllib.error.HTTPError) and e.code == 429
            if attempt < retries:
                if limited:
                    log(f"  Open-Meteo rate limit hit; waiting {RATE_LIMIT_WAIT_S} s...")
                time.sleep(RATE_LIMIT_WAIT_S if limited else 2 * (attempt + 1))
            elif limited:
                raise RateLimited(
                    "Open-Meteo's free hourly/daily allowance is used up for now - "
                    "progress is saved; run this again later to finish."
                ) from e
    raise RuntimeError(f"Open-Meteo fetch failed for ({lat}, {lon}): {last_err}")


def empty_cache() -> dict:
    return {
        "generated_at": None,
        "source": "Open-Meteo historical archive (ERA5), https://open-meteo.com",
        "period": {"start": PERIOD_START, "end": PERIOD_END},
        "thresholds": THRESHOLDS,
        "grid_deg": GRID_DEG,
        "complete": False,
        "projects": {},
    }


def build_climatology_cache(
    projects: list[dict],
    fetch=fetch_daily,
    pause: float = MIN_INTERVAL_S,
    existing: dict | None = None,
    save=None,
    log=lambda *_: None,
) -> dict:
    """Climatology for every project with a center point, one request per
    GRID_DEG cell. Starts from `existing` (skipping what it already has and
    reusing its cells) and calls `save(cache)` after each new cell, so an
    interrupted run loses nothing. A persistent rate limit stops the run early
    with `complete: False` instead of raising."""
    cache = json.loads(json.dumps(existing)) if existing else empty_cache()
    if existing and existing.get("grid_deg") != GRID_DEG:
        cache["projects"] = {}  # older cache on a different grid: start over
    cache.update(grid_deg=GRID_DEG, period={"start": PERIOD_START, "end": PERIOD_END}, thresholds=THRESHOLDS)
    cache.setdefault("generated_at", None)
    have = cache["projects"]
    known_cells = {(v["lat"], v["lon"]): v["monthly"] for v in have.values()}

    todo: dict[tuple[float, float], list[dict]] = {}
    for p in projects:
        if p.get("lat_center") is None or p.get("lon_center") is None or p["project_id"] in have:
            continue
        cell = grid_cell(p["lat_center"], p["lon_center"])
        if cell in known_cells:  # a neighbor already paid for this cell
            have[p["project_id"]] = {"lat": cell[0], "lon": cell[1], "monthly": known_cells[cell]}
        else:
            todo.setdefault(cell, []).append(p)

    def stamp():
        cache["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if todo:
        mins = math.ceil(len(todo) * pause / 60)
        log(f"  {len(todo)} location(s) to fetch, {pause:g} s apart (Open-Meteo free-tier pacing, ~{mins} min)")
    for i, ((lat, lon), members) in enumerate(todo.items(), start=1):
        if i > 1:
            time.sleep(pause)
        try:
            monthly = monthly_climatology(fetch(lat, lon))
        except RateLimited as e:
            log(f"  stopped at {i - 1}/{len(todo)}: {e}")
            break
        for p in members:
            have[p["project_id"]] = {"lat": lat, "lon": lon, "monthly": monthly}
        stamp()
        if save:
            save(cache)
        log(f"  [{i}/{len(todo)}] ({lat}, {lon}) -> {len(members)} project(s)")

    located = [p for p in projects if p.get("lat_center") is not None]
    cache["complete"] = all(p["project_id"] in have for p in located)
    if cache["generated_at"] is None:
        stamp()
    return cache


def fetch_to_file(projects: list[dict], out: Path, log=print, pause: float = MIN_INTERVAL_S, fetch=None) -> dict:
    """Build/resume the cache at `out`, writing it after every location."""
    existing = json.loads(out.read_text()) if out.exists() else None
    out.parent.mkdir(parents=True, exist_ok=True)
    def save(c):  # atomic, so the page never reads a half-written file
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_text(json.dumps(c, indent=1))
        tmp.replace(out)

    cache = build_climatology_cache(projects, fetch=fetch or fetch_daily, existing=existing, save=save, log=log, pause=pause)
    save(cache)
    return cache


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--projects", type=Path, default=DEFAULT_PROJECTS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    projects = json.loads(args.projects.read_text())
    print(f"Weather history ({PERIOD_START}..{PERIOD_END}) for {len(projects)} projects from Open-Meteo...")
    try:
        cache = fetch_to_file(projects, args.out)
    except RuntimeError as e:
        print(f"Could not reach Open-Meteo: {e}", file=sys.stderr)
        print("The weather panel will fetch the pair you click live instead.", file=sys.stderr)
        return 1
    n = len(cache["projects"])
    if cache["complete"]:
        print(f"Weather cache complete: {n} projects -> {args.out}")
        return 0
    print(f"Weather cache partial: {n} projects so far -> {args.out} (run again later to finish; "
          "the page fetches missing pairs live meanwhile)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
