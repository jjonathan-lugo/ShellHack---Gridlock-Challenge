"""Automatic ingest: PDF extraction, name parsing, geocode matching, and the
end-to-end pipeline checked against the hand-built spreadsheet."""

import copy
import json

import pytest

from backend.ingest.geocode import Match, OsmIndex, geocode_point, state_of
from backend.ingest.names import normalize_station, sub_points
from backend.overlap.timeline_overlap import _parse

from .conftest import REPO_ROOT

pdfplumber = pytest.importorskip("pdfplumber")
from backend.ingest import extract, pipeline  # noqa: E402  (needs pdfplumber)

PDFS_PRESENT = extract.DESC_PDF.exists() and extract.GPC_PDF.exists()
needs_pdfs = pytest.mark.skipif(not PDFS_PRESENT, reason="source PDFs not in data/")


# ---------- names ----------

@pytest.mark.parametrize(
    "name, expected",
    [
        ("Stevens Creek - Hooks 115kV/LR Plumb Branch 46kV Rebuilds", ["Stevens Creek", "Hooks"]),
        ("Hooks - Thurmond 115kV Tie: Rebuild", ["Hooks", "Thurmond"]),
        ("Jasper – Okatie 230 kV #2: Construct", ["Jasper", "Okatie"]),
        ("Okatie-Bluffton 115kV: Rebuild", ["Okatie", "Bluffton"]),
        ("Queensboro - Ft Johnson 115 kV & Queensboro-Bayfront 115kV (Queensboro-James Island Sect)", ["Queensboro", "Ft Johnson"]),
        ("EVANS PRIMARY - THURMOND DAM (USA) #5 115KV REBUILD", ["EVANS PRIMARY", "THURMOND DAM"]),
        ("SAV: MCINTOSH - PURRYSBURG 230KV REACTORS", ["MCINTOSH", "PURRYSBURG"]),
        ("SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD", ["GOSHEN", "MCINTOSH"]),
        ("MITCHELL - NORTH TIFTON 230KV RECONDUCTOR", ["MITCHELL", "NORTH TIFTON"]),
        ("JESUP - LUDOWICI PRIMARY 115KV REBUILD", ["JESUP", "LUDOWICI PRIMARY"]),
        ("Edenwood Sub: #1 & #2 230-115kV Autobanks, Replace with 336MVA", ["Edenwood"]),
        ("Church Creek – Faber Place – Charleston Transmission: Add 230kV Line", ["Church Creek", "Charleston"]),
        ("PLANT YATES BREAKER AND HALF STATION", ["PLANT YATES"]),
        ("GTC: CLIFTONDALE - LINE CREEK 230KV LINE", ["CLIFTONDALE", "LINE CREEK"]),
        ("THALMANN AND COLERAIN 23O KV LINE RELAY PANEL UPGRADES", ["THALMANN", "COLERAIN"]),
        ("GRID - BREMEN - CROOKED CREEK (APC) 115 KV PROJECT", ["BREMEN", "CROOKED CREEK"]),
        ("SMART VALVE INSTALLATION", []),
    ],
)
def test_sub_points(name, expected):
    assert sub_points(name) == expected


def test_normalize_station_equates_spellings():
    assert normalize_station("Stevens Creek Sub") == normalize_station("STEVENS CREEK SUBSTATION") == "STEVENS CREEK"
    assert normalize_station("THURMOND DAM #5") == "THURMOND DAM"
    assert normalize_station("WADLEY PRI.") == normalize_station("Wadley Primary") == "WADLEY"
    assert normalize_station("St George") == "SAINT GEORGE"
    assert normalize_station("Williams St") == "WILLIAMS STREET"
    assert normalize_station("GORDON-N DUBLIN") == "GORDON NORTH DUBLIN"


def test_curated_sub_point_names_are_recovered_from_project_titles(projects):
    """The spreadsheet's hand-entered sub-point names come out of the titles."""
    for p in projects:
        got = {normalize_station(n) for n in sub_points(p["project_name"])}
        for side in ("a", "b"):
            assert normalize_station(p[f"name_{side}"]) in got, (p["project_id"], p[f"name_{side}"], got)


# ---------- geocode matching ----------

def test_state_of_follows_savannah_river():
    assert state_of(33.47, -82.00) == "GA"  # Augusta
    assert state_of(33.50, -81.94) == "SC"  # North Augusta
    assert state_of(32.352, -81.18) == "GA"  # Plant McIntosh
    assert state_of(32.30, -81.10) == "SC"  # Purrysburg
    assert state_of(36.5, -80.0) is None


FEATURES = [
    {"id": "node/1", "name": "Evans Primary Substation", "lat": 33.544, "lon": -82.131, "operator": "Georgia Power", "power": "substation"},
    {"id": "node/2", "name": "Hooks", "lat": 33.70, "lon": -82.05, "operator": "Dominion Energy", "power": "substation"},
    # decoy: same name, wrong side of the river, other operator
    {"id": "node/3", "name": "Hooks", "lat": 33.40, "lon": -82.40, "operator": "", "power": "substation"},
    {"id": "node/4", "name": "Mitchel Substation", "lat": 31.45, "lon": -83.60, "operator": "", "power": "substation"},
    {"id": "node/5", "name": "Totally Unrelated", "lat": 32.0, "lon": -81.0, "operator": "", "power": "substation"},
]


def test_osm_matching_confidence_and_state_check():
    idx = OsmIndex(FEATURES)
    evans = idx.best("EVANS PRIMARY", "GA")
    assert (evans.osm_id, evans.confidence, evans.method) == ("node/1", "high", "osm")

    hooks = idx.best("Hooks", "SC")
    assert hooks.osm_id == "node/2" and hooks.confidence == "high"  # decoy in GA loses

    mitchell = idx.best("MITCHELL", "GA")  # misspelled in OSM, no operator
    assert mitchell.osm_id == "node/4" and mitchell.confidence in ("medium", "low")

    assert idx.best("Queensboro", "SC").method == "unmatched"


# Real bug, reproduced from the live run: OSM has two "Goshen Substation"s in
# Georgia 87 mi apart. Same name, same operator, so the name/operator/state
# score ties and picking either is a coin flip — unless the project's other
# endpoint (McIntosh, near the correct one) breaks the tie.
GOSHEN_FEATURES = FEATURES + [
    {"id": "way/near", "name": "Goshen Substation", "lat": 32.2487, "lon": -81.2095, "operator": "Georgia Power", "power": "substation"},
    {"id": "way/far", "name": "Goshen Substation", "lat": 33.3198, "lon": -81.9953, "operator": "Georgia Power", "power": "substation"},
]
MCINTOSH = (32.3521, -81.1751)


def test_tied_osm_names_are_broken_by_the_projects_other_endpoint():
    idx = OsmIndex(GOSHEN_FEATURES)

    # Without a hint the name can't decide — so it must not claim confidence.
    blind = idx.best("GOSHEN", "GA")
    assert blind.method == "osm"
    assert blind.ambiguous and blind.confidence == "low"

    # With the project's other endpoint (McIntosh) as a hint, the tie must
    # resolve to the Goshen that's actually near it, not the one 87 mi away.
    near_pick = idx.best("GOSHEN", "GA", near=MCINTOSH)
    assert near_pick.osm_id == "way/near"
    assert not near_pick.ambiguous
    assert near_pick.confidence in ("high", "medium")


def test_different_names_that_match_weakly_are_not_ambiguous():
    # From the real data: "Stevens Creek" weakly matches both of these, but
    # they're different stations — only a true same-name duplicate is ambiguous.
    idx = OsmIndex([
        {"id": "a", "name": "Stevens Creek Dam Substation", "lat": 33.5616, "lon": -82.0533, "operator": "", "power": "substation"},
        {"id": "b", "name": "Stevens Crossroads Switching Station", "lat": 32.9932, "lon": -80.8794, "operator": "", "power": "substation"},
    ])
    m = idx.best("Stevens Creek", "SC")
    assert m.osm_id == "a" and not m.ambiguous


def _index_with(*extra):
    return OsmIndex(GOSHEN_FEATURES + list(extra))


MCINTOSH_FEATURE = {"id": "node/mc", "name": "MCINTOSH", "lat": MCINTOSH[0], "lon": MCINTOSH[1], "operator": "Georgia Power", "power": "substation"}


@pytest.mark.parametrize("title", [
    "SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD",  # ambiguous name first
    "SAV: MCINTOSH - GOSHEN (SAV) 115KV LINE REBUILD",  # ambiguous name second
])
def test_locate_project_resolves_a_tied_name_from_either_side(title):
    idx = _index_with(MCINTOSH_FEATURE)

    def geocode(name, state, near=None):
        return geocode_point(name, state, idx, None, near=near)

    out = pipeline.locate_project({"utility": "Georgia Power", "state": "GA", "project_name": title, "source_id": "1"}, geocode)
    side = "a" if out["name_a"] == "GOSHEN" else "b"
    assert out[f"lat_{side}"] == pytest.approx(32.2487, abs=0.01)  # never the decoy 87 mi away
    assert out["location_confidence"] in ("high", "medium")


def test_locate_project_rejects_a_far_fallback_and_centers_on_the_good_end():
    """'Hooks' isn't in OSM; Nominatim's best guess is "Hooks Pond" on the
    coast, 165 mi from the line's other end. It must be dropped, leaving the
    project centered on Thurmond — what the hand-built spreadsheet does."""
    thurmond = {"id": "node/th", "name": "Thurmond Substation", "lat": 33.6601, "lon": -82.1959, "operator": "Dominion Energy", "power": "substation"}
    idx = OsmIndex([thurmond])  # no "Hooks" in OSM, as in the real data

    class FarNominatim:
        def search(self, q):
            if q.startswith("Hooks"):
                return [{"lat": "34.1706", "lon": "-79.0914", "category": "natural", "display_name": "Hooks Pond, Horry County"}]
            return []

    nom = FarNominatim()

    def geocode(name, state, near=None):
        return geocode_point(name, state, idx, nom, near=near)

    # Without a partner the fallback is all we have, so it's kept (low).
    assert geocode("Hooks", "SC").lat == pytest.approx(34.1706)

    out = pipeline.locate_project({"utility": "Dominion Energy SC", "state": "SC", "project_name": "Hooks - Thurmond 115kV Tie: Rebuild", "source_id": "6810A"}, geocode)
    assert out["lat_a"] is None  # Hooks Pond rejected
    assert (out["lat_center"], out["lon_center"]) == pytest.approx((33.6601, -82.1959))
    assert out["location_confidence"] == "low"  # one end missing: worth a look


def test_two_argument_geocoders_still_work():
    out = pipeline.locate_project(
        {"utility": "Georgia Power", "state": "GA", "project_name": "JESUP - LUDOWICI PRIMARY 115KV REBUILD", "source_id": "2"},
        lambda name, state: Match(query=name, lat=31.6, lon=-81.9, confidence="high", method="osm"),
    )
    assert out["lat_center"] == pytest.approx(31.6)


# Replays the live OSM + Nominatim responses cached by a real online run
# (data/cache/ is git-ignored, so this skips on a fresh clone).
REAL_CACHE = REPO_ROOT / "data" / "cache" / "osm_power_ga_sc.json"


@needs_pdfs
@pytest.mark.skipif(not REAL_CACHE.exists(), reason="no cached OSM data (run ./run-ingest.sh online once)")
def test_real_osm_data_recovers_every_spreadsheet_overlap(tmp_path):
    from backend.ingest.geocode import NOMINATIM_CACHE, Nominatim, fetch_osm_features

    index = OsmIndex(fetch_osm_features(offline=True))
    nom = Nominatim(cache=NOMINATIM_CACHE, offline=True)
    result = pipeline.run(
        geocode=lambda name, state, near=None: geocode_point(name, state, index, nom, near=near),
        out_dir=tmp_path, log=lambda *_: None,
    )
    v = result["report"]["vs_curated_spreadsheet"]
    assert v["curated_overlaps_missed"] == []
    by_id = {p["project_id"]: p for p in result["projects"]}
    for pid in ("GPC-20065", "GPC-20785"):  # both Goshen line projects land near Savannah
        assert by_id[pid]["lat_a"] == pytest.approx(32.2487, abs=0.01)
    for pid in ("DESC-6810A", "DESC-6809E"):  # "Hooks Pond" never used
        p = by_id[pid]
        assert all(p[f"lat_{s}"] is None for s in "ab" if p[f"name_{s}"] == "Hooks")
    from backend.overlap.geo_overlap import haversine_mi
    spans = [haversine_mi(p["lat_a"], p["lon_a"], p["lat_b"], p["lon_b"])
             for p in result["projects"] if p["lat_a"] is not None and p["lat_b"] is not None]
    assert max(spans) <= 75  # no line drawn across half the map
    assert by_id["GPC-13628"]["lat_b"] is not None  # "- SINAI (FPL)" kept: crosses into Florida for real


def test_nominatim_fallback_is_low_confidence_and_state_checked():
    class FakeNominatim:
        def __init__(self):
            self.queries = []

        def search(self, q):
            self.queries.append(q)
            if q.startswith("Queensboro substation"):
                return []
            if q.startswith("Queensboro,"):
                return [
                    {"lat": "32.08", "lon": "-81.20", "category": "place", "display_name": "wrong state"},
                    {"lat": "32.72", "lon": "-79.97", "category": "place", "display_name": "James Island, SC"},
                ]
            return []

    fake = FakeNominatim()
    m = geocode_point("Queensboro", "SC", OsmIndex(FEATURES), fake)
    assert (m.method, m.confidence, m.lat) == ("nominatim", "low", 32.72)
    assert fake.queries == ["Queensboro substation, South Carolina", "Queensboro, South Carolina"]
    assert geocode_point("Nowhere", "SC", None, None).method == "unmatched"


# ---------- extraction ----------

@pytest.fixture(scope="session")
def extracted():
    if not PDFS_PRESENT:
        pytest.skip("source PDFs not in data/")
    return extract.extract_desc_projects(), extract.extract_gpc_projects()


def test_desc_extraction(extracted):
    desc, _ = extracted
    assert len(desc) == 44
    assert [d["source_index"] for d in desc] == list(range(1, 45))
    assert all(d["in_service_date"] for d in desc)
    phased = next(d for d in desc if d["source_id"] == "6859")
    assert phased["in_service_date"] == "2026-10-01" and "phase 2" in phased["in_service_note"]
    first = desc[0]
    assert first["source_id"] == "6807 B" and first["estimated_cost_usd"] == 5404301


def test_gpc_extraction(extracted):
    _, gpc = extracted
    assert len(gpc) == 208
    assert len({g["source_id"] for g in gpc}) == 208
    gp = [g for g in gpc if g["sponsor"] in pipeline.GEORGIA_POWER_SPONSORS]
    assert len(gp) == 138
    evans = next(g for g in gpc if g["source_id"] == "20793")
    assert evans["project_name"] == "EVANS PRIMARY - THURMOND DAM (USA) #5 115KV REBUILD"
    assert evans["in_service_date"] == "2033-06-01"


def test_every_curated_project_is_in_the_pdfs_with_the_same_date(extracted, projects):
    desc, gpc = extracted
    for p in projects:
        pool = desc if p["project_id"].startswith("DESC") else gpc
        want = normalize_station(p["project_name"])
        match = max(pool, key=lambda r: _similar(want, normalize_station(r["project_name"])) + (
            0.05 if r["in_service_date"] == _parse(p["in_service_date"]).strftime("%Y-%m-%d") else 0))
        assert match["in_service_date"] == _parse(p["in_service_date"]).strftime("%Y-%m-%d"), p["project_id"]


def _similar(a, b):
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------- end to end ----------

def test_pipeline_reproduces_spreadsheet_overlaps(extracted, projects, spreadsheet_overlaps, monkeypatch, tmp_path):
    """Give the geocoder the spreadsheet's own coordinates: starting from nothing
    but the PDFs, the pipeline must find the same projects and every one of the
    spreadsheet's overlaps, at the same distances."""
    desc, gpc = extracted
    monkeypatch.setattr(pipeline, "extract_desc_projects", lambda *_: copy.deepcopy(desc))
    monkeypatch.setattr(pipeline, "extract_gpc_projects", lambda *_: copy.deepcopy(gpc))

    known = {}
    for p in projects:
        for side in ("a", "b"):
            if p[f"lat_{side}"] is not None:
                known[normalize_station(p[f"name_{side}"])] = (p[f"lat_{side}"], p[f"lon_{side}"])

    def fake_geocode(name, state):
        hit = known.get(normalize_station(name))
        if hit is None:
            return Match(query=name)
        return Match(query=name, lat=hit[0], lon=hit[1], confidence="high", method="osm", score=1.0)

    result = pipeline.run(geocode=fake_geocode, out_dir=tmp_path, log=lambda *_: None)
    report = result["report"]
    v = report["vs_curated_spreadsheet"]

    assert report["projects"] == {"desc": 44, "gpc": 138, "total": 182}
    assert v["curated_projects_found"] == len(projects)
    assert v["median_point_error_mi"] == 0.0  # every other point is exact
    assert v["curated_overlaps_missed"] == []
    assert sorted(v["curated_overlaps_recovered"]) == sorted(o["overlap_id"] for o in spreadsheet_overlaps)

    # The spreadsheet enters McIntosh twice with coordinates ~0.4 mi apart
    # (GPC_2 vs GPC_3). A name-based geocoder gives one station one location,
    # so pairs touching McIntosh may differ by up to that spread; the pipeline
    # reports the inconsistency rather than hiding it.
    inconsistent = {i["station"]: i for i in v["curated_inconsistencies"]}
    assert set(inconsistent) == {"MCINTOSH"}
    assert {e["project_id"] for e in inconsistent["MCINTOSH"]["entries"]} == {"GPC_2", "GPC_3"}
    slack = inconsistent["MCINTOSH"]["spread_mi"] + 0.01

    by_pair = {(o["project_id_a"], o["project_id_b"]): o for o in result["overlaps"]}
    for o in spreadsheet_overlaps:
        pair = (v["project_mapping"][o["project_id_a"]], v["project_mapping"][o["project_id_b"]])
        touches_mcintosh = {"GPC_2", "GPC_3"} & {o["project_id_a"], o["project_id_b"]}
        tol = slack if touches_mcintosh else 0.1
        assert by_pair[pair]["distance_mi"] == pytest.approx(o["distance_mi"], abs=tol)
        assert by_pair[pair]["time_gap (day)"] == o["time_gap (day)"]

    # Output files have the shape the UIs already read.
    written = json.loads((tmp_path / "overlaps_auto.json").read_text())
    assert set(spreadsheet_overlaps[0]) <= set(written[0])
    auto_projects = json.loads((tmp_path / "projects_auto.json").read_text())
    assert set(projects[0]) - {"overlap_count", "overlap_1", "overlap_2", "overlap_3"} <= set(auto_projects[0])


# ---------- region + span checks (from the live run) ----------

@pytest.mark.parametrize("place, lat, lon, inside", [
    ("Atlanta", 33.75, -84.39, True), ("Charleston SC", 32.78, -79.93, True),
    ("Myrtle Beach", 33.69, -78.89, True), ("Valdosta", 30.83, -83.28, True),
    ("Columbus GA", 32.46, -84.99, True), ("Rock Hill SC", 34.92, -81.02, True),
    ("Goat Rock Dam (on the GA-AL river line)", 32.61, -85.081, True),
    ("Grady Substation, Florida", 30.576, -85.031, False),
    ("Northwest Jax, Florida", 30.368, -81.685, False),
    ("Charleston Substation, Tennessee", 35.282, -84.774, False),
    ("West End Substation, North Carolina", 35.22, -79.53, False),
    ("Fayetteville, North Carolina", 35.021, -78.917, False),
    ("Opelika AL", 32.65, -85.38, False),
])
def test_in_region_is_georgia_plus_south_carolina(place, lat, lon, inside):
    from backend.ingest.geocode import in_region
    assert in_region(lat, lon) is inside, place


def test_out_of_state_namesakes_are_skipped_but_cross_border_partners_allowed():
    idx = OsmIndex([
        {"id": "fl", "name": "Grady Substation", "lat": 30.576, "lon": -85.031, "operator": "", "power": "substation"},
        {"id": "sinai", "name": "Sinai Substation", "lat": 30.664, "lon": -84.901, "operator": "", "power": "substation"},
    ])
    assert idx.best("GRADY", "GA").method == "unmatched"  # only a Florida one exists
    assert idx.best("SINAI", "GA").method == "unmatched"  # no partner: out of state
    south_bainbridge = (30.87, -84.60)  # "SOUTH BAINBRIDGE - SINAI (FPL)": 27 mi away
    assert idx.best("SINAI", "GA", near=south_bainbridge).osm_id == "sinai"
    assert idx.best("GRADY", "GA", near=(33.606, -84.333)).method == "unmatched"  # 213 mi from Morrow


def test_a_pair_too_far_apart_keeps_the_more_trustworthy_end():
    """Both ends matched, 326 mi apart ('Williams-Summerville'): the weaker
    match is dropped rather than averaging them into a meaningless midpoint."""
    idx = OsmIndex([
        {"id": "w", "name": "Williams Substation", "lat": 33.018, "lon": -79.932, "operator": "Dominion Energy", "power": "substation"},
        {"id": "s", "name": "Summerville Substation", "lat": 34.472, "lon": -85.338, "operator": "", "power": "substation"},
    ])
    out = pipeline.locate_project(
        {"utility": "Dominion Energy SC", "state": "SC", "project_name": "Williams-Summerville 230kV: Upgrade", "source_id": "6388A"},
        lambda name, state, near=None: geocode_point(name, state, idx, None, near=near),
    )
    assert (out["lat_center"], out["lon_center"]) == pytest.approx((33.018, -79.932))
    assert out["lat_b"] is None and out["geocode_b"]["method"] == "rejected_too_far"
    assert out["location_confidence"] == "low"
