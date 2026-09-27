"""PDFs -> projects -> coordinates -> overlaps, end to end.

    pip install -r backend/requirements-ingest.txt       # pdfplumber + pypdf
    python3 -m backend.ingest.pipeline                   # full run (needs internet the first time)
    python3 -m backend.ingest.pipeline --offline         # reuse cached OSM/Nominatim lookups only
    python3 -m backend.ingest.pipeline --weather         # also cache weather for the new projects

Writes data/processed/auto/:
    projects_auto.json     same shape as data/processed/projects.json, plus
                           geocode confidence per sub-point
    overlaps_auto.json     same shape as data/processed/overlaps.json
    ingest_report.json     coverage, confidence mix, and a check against the
                           hand-geocoded spreadsheet (coordinate error per point,
                           which of its overlaps were recovered)

Both UIs pick the auto dataset up automatically and offer a dataset switch.
"""

from __future__ import annotations

import argparse
import difflib
import inspect
import json
import statistics
import sys
from pathlib import Path

from backend.ingest.extract import DESC_PDF, GPC_PDF, extract_desc_projects, extract_gpc_projects
from backend.ingest.geocode import MAX_SPAN_MI, Match, Nominatim, OsmIndex, fetch_osm_features, geocode_point
from backend.ingest.names import normalize_station, sub_points
from backend.overlap.geo_overlap import haversine_mi
from backend.overlap.score import build_ranked_overlaps

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED = REPO_ROOT / "data" / "processed"
AUTO_DIR = PROCESSED / "auto"
GEORGIA_POWER_SPONSORS = {"GPC", "SAV"}  # SAV = Georgia Power's Savannah area
CONFIDENCE_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _project_id(rec: dict) -> str:
    prefix = "DESC" if rec["utility"].startswith("Dominion") else "GPC"
    return f"{prefix}-{rec['source_id'].replace(' ', '')}"


def _anchor(m: Match) -> tuple[float, float] | None:
    """A located sub-point trustworthy enough to steer its partner's lookup:
    a real, unambiguous substation match, or anything medium/high. A
    low-confidence place-name fallback (e.g. "Hooks Pond") or a coin-flip
    between same-named substations is not."""
    if m.lat is None or m.ambiguous:
        return None
    if m.method == "osm" or CONFIDENCE_RANK[m.confidence] >= CONFIDENCE_RANK["medium"]:
        return (m.lat, m.lon)
    return None


def locate_project(rec: dict, geocode) -> dict:
    """Project record in the projects.json shape, with its sub-points geocoded.

    The two sub-points are one project (a line's two ends), so each is
    re-located next to the other. That fixes two failure modes seen on the
    real data: OSM has two "Goshen Substation"s 87 mi apart (a name tie the
    partner endpoint breaks), and "Hooks" isn't in OSM, so the fallback found
    "Hooks Pond" 165 mi away (rejected as too far from the partner — the
    project centers on its one good endpoint, as the spreadsheet does).
    Geocode callables that only take (name, state) still work, without hints.
    """
    state = rec.get("state")
    names = sub_points(rec["project_name"])
    while len(names) < 2:
        names.append(None)
    takes_near = "near" in inspect.signature(geocode).parameters

    def call(name, near=None):
        if name is None:
            return Match(query="")
        return geocode(name, state, near=near) if takes_near else geocode(name, state)

    # Locate both ends independently, then re-locate each one next to the
    # other. Only a real substation match (OSM) or a medium+/high result is
    # trusted as the reference — never a fuzzy place-name fallback.
    a, b = call(names[0]), call(names[1])
    if takes_near:
        for _ in range(2):  # second round settles on the corrected partner
            a, b = call(names[0], near=_anchor(b)), call(names[1], near=_anchor(a))

    # Two ends of one line can't be hundreds of miles apart: one of them is a
    # wrong match. Keep the more trustworthy end; the project is then flagged
    # low-confidence below (a named end is missing).
    if a.lat is not None and b.lat is not None and haversine_mi(a.lat, a.lon, b.lat, b.lon) > MAX_SPAN_MI:
        trust = lambda m: (CONFIDENCE_RANK[m.confidence], m.method == "osm", not m.ambiguous, m.score)  # noqa: E731
        weaker = min((a, b), key=trust)
        dropped = Match(query=weaker.query, method="rejected_too_far", matched_name=weaker.matched_name, osm_id=weaker.osm_id)
        a, b = (dropped, b) if weaker is a else (a, dropped)

    matches: list[Match] = [a, b]
    located = [m for m in matches if m.lat is not None]
    if located:
        lat_c = sum(m.lat for m in located) / len(located)
        lon_c = sum(m.lon for m in located) / len(located)
        worst = min(located, key=lambda m: CONFIDENCE_RANK[m.confidence]).confidence
        named_but_missing = any(n and m.lat is None for n, m in zip(names, matches))
        if named_but_missing and CONFIDENCE_RANK[worst] > CONFIDENCE_RANK["low"]:
            worst = "low"  # center falls back to one endpoint — worth a look
    else:
        lat_c = lon_c = None
        worst = "none"

    a, b = matches
    out = {
        "project_id": _project_id(rec),
        "utility": rec["utility"],
        "state": rec.get("state"),
        "project_name": rec["project_name"],
        "name_a": names[0],
        "lat_a": a.lat,
        "lon_a": a.lon,
        "name_b": names[1],
        "lat_b": b.lat,
        "lon_b": b.lon,
        "lat_center": lat_c,
        "lon_center": lon_c,
        "in_service_date": rec.get("in_service_date"),
        "source": "pdf",
        "source_id": rec["source_id"],
        "sponsor": rec.get("sponsor"),
        "status": rec.get("status"),
        "location_confidence": worst,
        "geocode_a": a.to_dict() if names[0] else None,
        "geocode_b": b.to_dict() if names[1] else None,
    }
    if rec.get("in_service_note"):
        out["in_service_note"] = rec["in_service_note"]
    return out


def to_overlap_table(ranked: list[dict], by_id: dict) -> list[dict]:
    """Same row shape as data/processed/overlaps.json (the spreadsheet export)."""
    rows = []
    for o in ranked:
        pa, pb = by_id[o["project_id_a"]], by_id[o["project_id_b"]]
        conf = min(pa["location_confidence"], pb["location_confidence"], key=CONFIDENCE_RANK.get)
        rows.append(
            {
                "overlap_id": f"AUTO_{o['rank']}",
                "distance_mi": round(o["distance_mi"], 2),
                "time_gap (day)": o["time_gap_days"],
                "utility_a": o["utility_a"],
                "project_id_a": o["project_id_a"],
                "project_name_a": o["project_name_a"],
                "utility_b": o["utility_b"],
                "project_id_b": o["project_id_b"],
                "project_name_b": o["project_name_b"],
                "location_confidence": conf,
            }
        )
    return rows


# ---------------- comparison with the hand-geocoded spreadsheet ----------------

def _same_project(curated: dict, auto: list[dict]) -> dict | None:
    """The auto project that corresponds to a hand-curated one (same utility,
    closest name, same in-service date breaking ties)."""
    target = normalize_station(curated["project_name"])
    best, best_key = None, None
    for p in auto:
        if p["utility"] != curated["utility"]:
            continue
        ratio = difflib.SequenceMatcher(None, target, normalize_station(p["project_name"])).ratio()
        same_date = _iso(curated.get("in_service_date")) == p.get("in_service_date")
        key = (ratio + (0.05 if same_date else 0), same_date)
        if best_key is None or key > best_key:
            best, best_key = p, key
    return best if best_key and best_key[0] >= 0.8 else None


def _iso(date_str: str | None) -> str | None:
    from backend.overlap.timeline_overlap import _parse

    d = _parse(date_str)
    return d.strftime("%Y-%m-%d") if d else None


def curated_inconsistencies(curated: list[dict], tolerance_mi: float = 0.1) -> list[dict]:
    """Same station name entered with different coordinates in the hand-built
    table (a data-entry check the automated pipeline makes possible)."""
    seen: dict[str, list[tuple[str, float, float]]] = {}
    for p in curated:
        for side in ("a", "b"):
            if p.get(f"lat_{side}") is None:
                continue
            key = normalize_station(p.get(f"name_{side}") or "")
            if not key:
                continue
            seen.setdefault(key, []).append((p["project_id"], p[f"lat_{side}"], p[f"lon_{side}"]))
    out = []
    for key, pts in seen.items():
        spread = max(
            (haversine_mi(a[1], a[2], b[1], b[2]) for i, a in enumerate(pts) for b in pts[i + 1 :]),
            default=0.0,
        )
        if spread > tolerance_mi:
            out.append({"station": key, "spread_mi": round(spread, 2),
                        "entries": [{"project_id": pid, "lat": la, "lon": lo} for pid, la, lo in pts]})
    return out


def compare_with_curated(auto: list[dict], auto_overlaps: list[dict], curated: list[dict], curated_overlaps: list[dict]) -> dict:
    mapping, point_errors = {}, []
    for c in curated:
        a = _same_project(c, auto)
        if a is None:
            continue
        mapping[c["project_id"]] = a["project_id"]
        for side in ("a", "b"):
            if c.get(f"lat_{side}") is None:
                continue
            # compare against whichever auto sub-point has the same name
            cname = normalize_station(c.get(f"name_{side}") or "")
            for s2 in ("a", "b"):
                if a.get(f"lat_{s2}") is None:
                    continue
                if difflib.SequenceMatcher(None, cname, normalize_station(a.get(f"name_{s2}") or "")).ratio() >= 0.8:
                    err = haversine_mi(c[f"lat_{side}"], c[f"lon_{side}"], a[f"lat_{s2}"], a[f"lon_{s2}"])
                    point_errors.append({"curated": c[f"name_{side}"], "auto": a[f"name_{s2}"], "error_mi": round(err, 2),
                                         "confidence": (a.get(f"geocode_{s2}") or {}).get("confidence")})
                    break

    auto_pairs = {(o["project_id_a"], o["project_id_b"]) for o in auto_overlaps}
    recovered, missed = [], []
    for o in curated_overlaps:
        pair = (mapping.get(o["project_id_a"]), mapping.get(o["project_id_b"]))
        (recovered if pair in auto_pairs else missed).append(o["overlap_id"])

    errs = [e["error_mi"] for e in point_errors]
    return {
        "curated_inconsistencies": curated_inconsistencies(curated),
        "curated_projects_found": len(mapping),
        "curated_projects_total": len(curated),
        "project_mapping": mapping,
        "points_compared": len(point_errors),
        "median_point_error_mi": round(statistics.median(errs), 2) if errs else None,
        "points_within_1_mi": sum(e <= 1 for e in errs),
        "point_errors": point_errors,
        "curated_overlaps_recovered": recovered,
        "curated_overlaps_missed": missed,
    }


# ---------------- run ----------------

def run(
    geocode=None,
    include_partners: bool = False,
    desc_pdf: Path = DESC_PDF,
    gpc_pdf: Path = GPC_PDF,
    out_dir: Path | None = AUTO_DIR,
    log=print,
) -> dict:
    """Whole pipeline. `geocode(name, state) -> Match` is injectable for tests."""
    log("Extracting DESC projects...")
    desc_raw = extract_desc_projects(desc_pdf)
    log(f"  {len(desc_raw)} DESC projects")
    log("Extracting Georgia ITS 10-year plan table (this PDF is 668 pages; ~10 s)...")
    gpc_all = extract_gpc_projects(gpc_pdf)
    gpc_raw = gpc_all if include_partners else [r for r in gpc_all if r["sponsor"] in GEORGIA_POWER_SPONSORS]
    log(f"  {len(gpc_all)} rows, {len(gpc_raw)} kept ({'all sponsors' if include_partners else 'Georgia Power: GPC + SAV'})")

    total = len(desc_raw) + len(gpc_raw)
    log(f"Geocoding sub-points for {total} projects (first run can take a few minutes)...")
    located_so_far = 0

    def locate(r, i):
        nonlocal located_so_far
        p = locate_project(r, geocode)
        located_so_far += p["lat_center"] is not None
        if i % 20 == 0 or i == total:
            log(f"  {i}/{total} projects processed, {located_so_far} located")
        return p

    desc = [locate(r, i) for i, r in enumerate(desc_raw, start=1)]
    gpc = [locate(r, i) for i, r in enumerate(gpc_raw, start=len(desc_raw) + 1)]
    projects = desc + gpc
    by_id = {p["project_id"]: p for p in projects}

    ranked = build_ranked_overlaps(
        [p for p in desc if p["lat_center"] is not None],
        [p for p in gpc if p["lat_center"] is not None],
    )
    overlaps = to_overlap_table(ranked, by_id)

    conf_mix = {k: sum(p["location_confidence"] == k for p in projects) for k in CONFIDENCE_RANK}
    report = {
        "projects": {"desc": len(desc), "gpc": len(gpc), "total": len(projects)},
        "located": sum(p["lat_center"] is not None for p in projects),
        "location_confidence": conf_mix,
        "overlaps": len(overlaps),
        "overlaps_by_confidence": {k: sum(o["location_confidence"] == k for o in overlaps) for k in CONFIDENCE_RANK},
    }
    curated_path = PROCESSED / "projects.json"
    if curated_path.exists():
        report["vs_curated_spreadsheet"] = compare_with_curated(
            projects, overlaps,
            json.loads(curated_path.read_text()),
            json.loads((PROCESSED / "overlaps.json").read_text()),
        )

    # Nothing located almost always means no network: keep the previous
    # outputs rather than replacing them with an empty dataset.
    report["written"] = out_dir is not None and report["located"] > 0
    if report["written"]:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "projects_auto.json").write_text(json.dumps(projects, indent=1))
        (out_dir / "overlaps_auto.json").write_text(json.dumps(overlaps, indent=1))
        (out_dir / "ingest_report.json").write_text(json.dumps(report, indent=1))
    return {"projects": projects, "overlaps": overlaps, "report": report}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="use cached lookups only; no network")
    ap.add_argument("--refresh-osm", action="store_true", help="re-download the OSM substation list")
    ap.add_argument("--no-nominatim", action="store_true", help="OSM matches only, no Nominatim fallback")
    ap.add_argument("--include-partners", action="store_true", help="also keep GTC / MEAG / DU rows")
    ap.add_argument("--weather", action="store_true", help="also fetch weather history for the auto projects")
    args = ap.parse_args(argv)

    try:
        print("Loading OpenStreetMap power substations for GA + SC (one Overpass query, cached)...")
        index = OsmIndex(fetch_osm_features(refresh=args.refresh_osm, offline=args.offline))
        print(f"  {len(index.features)} named substations/plants")
    except RuntimeError as e:
        print(f"  OSM unavailable ({e}); continuing with Nominatim only")
        index = None
    nominatim = None if args.no_nominatim else Nominatim(offline=args.offline)

    def geocode(name, state, near=None):
        return geocode_point(name, state, index, nominatim, near=near)

    try:
        result = run(geocode=geocode, include_partners=args.include_partners)
    except RuntimeError as e:  # e.g. pdfplumber missing
        print(e, file=sys.stderr)
        return 1
    finally:
        if nominatim is not None:
            nominatim.save()

    r = result["report"]
    if not r["written"]:
        print("\nCouldn't locate any project — is this machine online? (Overpass and Nominatim are "
              "needed the first time; later runs reuse data/cache/.) Previous outputs left untouched.",
              file=sys.stderr)
        return 1
    print(f"\nLocated {r['located']}/{r['projects']['total']} projects "
          f"(confidence: {r['location_confidence']})")
    print(f"Found {r['overlaps']} cross-utility overlaps under 25 mi "
          f"(by weakest location confidence: {r['overlaps_by_confidence']})")
    v = r.get("vs_curated_spreadsheet")
    if v:
        print(f"Check vs hand-geocoded spreadsheet: matched {v['curated_projects_found']}/{v['curated_projects_total']} projects; "
              f"median point error {v['median_point_error_mi']} mi over {v['points_compared']} points; "
              f"recovered {len(v['curated_overlaps_recovered'])}/{len(v['curated_overlaps_recovered']) + len(v['curated_overlaps_missed'])} of its overlaps")
    if v:
        for inc in v["curated_inconsistencies"]:
            ids = ", ".join(e["project_id"] for e in inc["entries"])
            print(f"  note: the spreadsheet places {inc['station']} at different points "
                  f"{inc['spread_mi']} mi apart ({ids}) — worth reconciling")
    print(f"Wrote {AUTO_DIR.relative_to(REPO_ROOT)}/projects_auto.json, overlaps_auto.json, ingest_report.json")

    if args.weather:
        from backend.weather.fetch import fetch_to_file

        # The weather panel shows overlap pairs, and Open-Meteo's free tier
        # allows only ~38 ten-year histories a day, so fetch just the projects
        # that are in an overlap. The page fetches anything else on click.
        in_overlaps = {o["project_id_a"] for o in result["overlaps"]} | {o["project_id_b"] for o in result["overlaps"]}
        targets = [p for p in result["projects"] if p["lat_center"] is not None and p["project_id"] in in_overlaps]
        out = AUTO_DIR / "weather_climatology_auto.json"
        print(f"Fetching weather history for the {len(targets)} projects in overlaps (resumes if interrupted)...")
        try:
            cache = fetch_to_file(targets, out)
            state = "complete" if cache["complete"] else "partial - run again later to finish"
            print(f"  weather cache {state}: {len(cache['projects'])} projects -> {out.relative_to(REPO_ROOT)}")
        except RuntimeError as e:
            print(f"  weather skipped: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
