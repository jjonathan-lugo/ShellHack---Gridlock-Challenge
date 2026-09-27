"""Geocode project sub-points against OpenStreetMap, the way the Sperry Tech
guide describes — then flag how much to trust each match.

1. One bulk Overpass query pulls every named power substation / plant in the
   GA + SC bounding box ("query for all of a utility's tagged infrastructure at
   once ... then filter down to the features whose names match").
2. Each sub-point name is fuzzy-matched against those features. The score
   rewards the right operator (Dominion / SCE&G vs Georgia Power / Southern)
   and the right side of the Savannah River, since "a similarly-named
   substation in the wrong zone or county is a common false match" (guide Part 2).
3. Anything without a good OSM match falls back to Nominatim.

Confidence: high (near-exact name + right operator or state), medium (strong
name match), low (weak match or Nominatim place fallback — check it by hand).

Standard library only. Responses are cached under data/cache/ so re-runs are
offline and polite to the free services.
"""

from __future__ import annotations

import difflib
import math
import json
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path

from backend.ingest.names import normalize_station
from backend.net import CERT_HELP, get_json, is_cert_error
from backend.overlap.geo_overlap import haversine_mi

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
OSM_CACHE = CACHE_DIR / "osm_power_ga_sc.json"
NOMINATIM_CACHE = CACHE_DIR / "nominatim.json"

# south, west, north, east — Georgia + South Carolina
BBOX = (30.3, -85.7, 35.3, -78.4)
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "gridlock-shellhacks/1.0 (utility coordination hackathon project)"

OPERATOR_HINTS = {
    "SC": ("DOMINION", "SCE&G", "SCANA", "SOUTH CAROLINA ELECTRIC"),
    "GA": ("GEORGIA POWER", "SOUTHERN COMPANY", "GEORGIA TRANSMISSION", "SAVANNAH ELECTRIC"),
}
STATE_NAMES = {"SC": "South Carolina", "GA": "Georgia"}

# Savannah River (the GA/SC border), south to north, as (lat, lon). West of the
# line is Georgia; east is South Carolina. Coarse, used only as a soft check.
_SAVANNAH_RIVER = [
    (32.03, -80.88), (32.08, -81.09), (32.22, -81.13), (32.35, -81.155),
    (32.55, -81.33), (32.94, -81.50), (33.14, -81.745), (33.35, -81.90),
    (33.47, -81.955), (33.56, -82.045), (33.66, -82.20), (34.00, -82.60),
    (34.35, -82.83), (34.68, -83.10), (35.00, -83.11),
]

# Coarse outline of Georgia + South Carolina together, as (lat, lon), clockwise
# from Georgia's NW corner. The query box (BBOX) is a rectangle, so it also
# covers parts of FL, AL, TN and NC — which have their own "Grady", "West End"
# and "Charleston" substations. Both utilities build only inside GA/SC, so
# anything outside this outline is the wrong place. Accurate to a few miles;
# coastal points are padded seaward so shoreline plants stay inside.
_GA_SC_OUTLINE = [
    (35.00, -85.61), (35.00, -83.11),                    # GA–TN/NC line
    (35.21, -82.40), (35.19, -81.04), (35.10, -80.94),   # SC–NC line
    (34.82, -80.80), (34.82, -79.68), (33.84, -78.50),
    (33.30, -78.90), (32.60, -79.70), (32.00, -80.70),   # coast, padded seaward
    (31.00, -81.10), (30.70, -81.30),
    (30.71, -81.44), (30.36, -82.04), (30.57, -82.21),   # GA–FL line
    (30.71, -84.86), (31.00, -85.00),
    (31.60, -85.08), (32.30, -85.00), (32.47, -85.01),   # GA–AL line (Chattahoochee)
    (32.85, -85.18),
]


BORDER_MARGIN_MI = 2  # the outline is approximate; border-river plants (Goat Rock Dam) count
CROSS_BORDER_MI = 30  # an out-of-state end is OK this close to an in-state partner (e.g. "- SINAI (FPL)")


def _outline_distance_mi(lat: float, lon: float) -> float:
    """Approximate distance from a point to the _GA_SC_OUTLINE boundary."""
    kx, ky = 69.17 * math.cos(math.radians(lat)), 69.0  # miles per degree
    best = float("inf")
    pts = _GA_SC_OUTLINE
    for (la1, lo1), (la2, lo2) in zip(pts, pts[1:] + pts[:1]):
        ax, ay, bx, by = lo1 * kx, la1 * ky, lo2 * kx, la2 * ky
        px, py = lon * kx, lat * ky
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


def in_region(lat: float, lon: float) -> bool:
    """Inside Georgia or South Carolina (ray casting on _GA_SC_OUTLINE), or
    within BORDER_MARGIN_MI of its edge."""
    inside = False
    pts = _GA_SC_OUTLINE
    for (la1, lo1), (la2, lo2) in zip(pts, pts[1:] + pts[:1]):
        if (lo1 > lon) != (lo2 > lon):
            if lat < la1 + (lon - lo1) * (la2 - la1) / (lo2 - lo1):
                inside = not inside
    return inside or _outline_distance_mi(lat, lon) <= BORDER_MARGIN_MI


def _allowed(lat: float, lon: float, near: tuple[float, float] | None) -> bool:
    """In GA/SC — or just across the line from the project's other end."""
    return in_region(lat, lon) or (near is not None and haversine_mi(near[0], near[1], lat, lon) <= CROSS_BORDER_MI)


HIGH, MEDIUM, LOW = 0.93, 0.84, 0.72

# A fallback (place-name) match farther than this from the project's other,
# already-located endpoint is rejected: transmission line rebuilds in these
# plans don't span that far, so it's the wrong place (e.g. "Hooks Pond",
# 165 mi from Hooks substation's real partner endpoints).
MAX_SPAN_MI = 75

# Two OSM candidates scoring within this margin of each other, farther apart
# than AMBIGUITY_MI, make a match ambiguous (confidence capped at "low").
AMBIGUITY_MARGIN = 0.02
AMBIGUITY_MI = 5


def state_of(lat: float, lon: float) -> str | None:
    """'GA' or 'SC' by which side of the Savannah River a point is on
    (None outside the river's latitude span)."""
    pts = _SAVANNAH_RIVER
    if lat < pts[0][0] or lat > pts[-1][0]:
        return None
    for (la1, lo1), (la2, lo2) in zip(pts, pts[1:]):
        if la1 <= lat <= la2:
            t = (lat - la1) / (la2 - la1) if la2 != la1 else 0
            border_lon = lo1 + t * (lo2 - lo1)
            return "SC" if lon > border_lon else "GA"
    return None


# ---------------- data sources ----------------

def overpass_query(bbox=BBOX) -> str:
    s, w, n, e = bbox
    return f"""[out:json][timeout:180];
(
  nwr["power"="substation"]["name"]({s},{w},{n},{e});
  nwr["power"="plant"]["name"]({s},{w},{n},{e});
);
out center tags;"""


def _http_json(url: str, data: bytes | None = None, timeout: float = 200) -> dict | list:
    return get_json(url, data=data, timeout=timeout)


def fetch_osm_features(cache: Path = OSM_CACHE, refresh: bool = False, offline: bool = False) -> list[dict]:
    """All named substations/plants in the bbox as [{id, name, lat, lon, operator, power}]."""
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    if offline:
        raise RuntimeError(f"No OSM cache at {cache} and --offline was given")

    body = urllib.parse.urlencode({"data": overpass_query()}).encode()
    last_err: Exception | None = None
    for url in OVERPASS_URLS:
        try:
            payload = _http_json(url, data=body)
            break
        except Exception as e:  # try the next mirror
            last_err = e
            if is_cert_error(e):
                raise RuntimeError(CERT_HELP) from e
    else:
        raise RuntimeError(f"Overpass unreachable: {last_err}")

    features = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        if lat is None or lon is None or not tags.get("name"):
            continue
        features.append(
            {
                "id": f"{el['type']}/{el['id']}",
                "name": tags["name"],
                "lat": lat,
                "lon": lon,
                "operator": tags.get("operator", ""),
                "power": tags.get("power", ""),
            }
        )
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(features))
    return features


class Nominatim:
    """Rate-limited (1 req/s, per the usage policy), cached Nominatim client.
    Gives up after a few consecutive network failures instead of crawling
    through hundreds of doomed 1-second-spaced requests."""

    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, cache: Path = NOMINATIM_CACHE, offline: bool = False, log=print):
        self.cache_path = cache
        self.offline = offline
        self.log = log
        self.cache: dict[str, list] = json.loads(cache.read_text()) if cache.exists() else {}
        self._last = 0.0
        self._failures = 0
        self.disabled_reason: str | None = None

    def search(self, query: str) -> list[dict]:
        if query in self.cache:
            return self.cache[query]
        if self.offline or self.disabled_reason:
            return []
        wait = 1.1 - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        s, w, n, e = BBOX
        params = {
            "q": query, "format": "jsonv2", "limit": 3, "countrycodes": "us",
            "viewbox": f"{w},{n},{e},{s}", "bounded": 1,
        }
        self._last = time.time()
        try:
            results = _http_json(f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}", timeout=30)
        except Exception as e:
            # Network failure: not cached, so the next online run retries.
            self._failures += 1
            if is_cert_error(e) or self._failures >= self.MAX_CONSECUTIVE_FAILURES:
                self.disabled_reason = CERT_HELP if is_cert_error(e) else f"Nominatim unreachable ({e})"
                self.log(f"  Nominatim fallback turned off: {self.disabled_reason}")
            return []
        self._failures = 0
        self.cache[query] = results
        return results

    def save(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache))


# ---------------- matching ----------------

@dataclass
class Match:
    query: str
    lat: float | None = None
    lon: float | None = None
    confidence: str = "none"  # high | medium | low | none
    method: str = "unmatched"  # osm | nominatim | unmatched
    matched_name: str | None = None
    osm_id: str | None = None
    score: float = 0.0
    ambiguous: bool = False  # an equally good same-name match exists elsewhere

    def to_dict(self) -> dict:
        return asdict(self)


class OsmIndex:
    def __init__(self, features: list[dict]):
        self.features = features
        self.by_token: dict[str, list[int]] = {}
        self.norm: list[str] = []
        for i, f in enumerate(features):
            n = normalize_station(f["name"])
            self.norm.append(n)
            for key in self._keys(n):
                self.by_token.setdefault(key, []).append(i)

    @staticmethod
    def _keys(normalized: str) -> set[str]:
        # 4-letter prefixes, so near-spellings ("MITCHEL" / "MITCHELL") still
        # become candidates for the fuzzy score.
        return {tok[:4] for tok in normalized.split() if len(tok) >= 3}

    def best(self, name: str, state: str | None, near: tuple[float, float] | None = None) -> Match:
        """`near`, when given, is another already-located sub-point of the same
        project (e.g. the line's other end). Two identically-named substations
        happen (OSM has two "Goshen Substation"s 87 mi apart) — a tied name
        score can't tell them apart, but the correct one is always the one
        near the project's other endpoint, per the guide's "wrong zone or
        county" warning, so it breaks the tie without overriding a real
        difference in name quality."""
        q = normalize_station(name)
        m = Match(query=name)
        if not q:
            return m
        candidates = {i for key in self._keys(q) for i in self.by_token.get(key, [])}
        best_key = None
        scored: list[tuple[float, float, float, str]] = []  # (score, lat, lon, name) for the ambiguity check
        best_norm = ""
        for i in sorted(candidates):  # sorted: ties resolve the same way every run
            f = self.features[i]
            if not _allowed(f["lat"], f["lon"], near):  # FL/AL/TN/NC namesakes
                continue
            ratio = difflib.SequenceMatcher(None, q, self.norm[i]).ratio()
            if ratio < LOW - 0.1:
                continue
            op_ok = state is not None and any(h in f["operator"].upper() for h in OPERATOR_HINTS.get(state, ()))
            f_state = state_of(f["lat"], f["lon"])
            state_ok = state is not None and f_state == state
            state_bad = state is not None and f_state is not None and f_state != state
            score = ratio + (0.05 if op_ok else 0) + (0.03 if state_ok else 0) - (0.12 if state_bad else 0)
            if near is not None:
                dist = haversine_mi(near[0], near[1], f["lat"], f["lon"])
                score -= min(0.15, dist / 300)
            scored.append((score, f["lat"], f["lon"], self.norm[i]))
            key = (score, f["power"] == "substation", op_ok)
            if best_key is None or key > best_key:
                best_key = key
                best_norm = self.norm[i]
                m.lat, m.lon = f["lat"], f["lon"]
                m.matched_name, m.osm_id = f["name"], f["id"]
                m.score = round(score, 3)
                corroborated = op_ok or state_ok
        if best_key is None or m.score < LOW:
            return Match(query=name)
        m.method = "osm"
        # The same station name, scoring just as well, somewhere else means the
        # name alone can't say which one it is (a one-name project like
        # "GOSHEN AREA STRATEGIC SOLUTION" has no partner endpoint to decide)
        # — never call that high. Different names that fuzzy-match equally
        # weakly ("Stevens Creek" vs "Stevens Crossroads") aren't this case.
        ambiguous = any(
            n == best_norm and s >= m.score - AMBIGUITY_MARGIN
            and haversine_mi(m.lat, m.lon, la, lo) > AMBIGUITY_MI
            for s, la, lo, n in scored
        )
        if ambiguous:
            m.confidence, m.ambiguous = "low", True
        elif m.score >= HIGH and corroborated:
            m.confidence = "high"
        elif m.score >= MEDIUM:
            m.confidence = "medium"
        else:
            m.confidence = "low"
        return m


def geocode_point(
    name: str,
    state: str | None,
    index: OsmIndex | None,
    nominatim: Nominatim | None,
    near: tuple[float, float] | None = None,
) -> Match:
    """Best location for one named sub-point. `near` (another already-located
    sub-point of the same project) breaks ties between identically-named
    OSM features in different places."""
    if index is not None:
        m = index.best(name, state, near=near)
        if m.method == "osm":
            return m
    if nominatim is None:
        return Match(query=name)

    state_name = STATE_NAMES.get(state or "", "")
    # A substation feature by that name first; otherwise the place itself.
    for query in (f"{name} substation, {state_name}", f"{name}, {state_name}"):
        results = nominatim.search(query.strip(", "))
        if near is not None:  # closest first; a line doesn't span 150+ miles
            results = sorted(results, key=lambda r: haversine_mi(near[0], near[1], float(r["lat"]), float(r["lon"])))
        for r in results:
            lat, lon = float(r["lat"]), float(r["lon"])
            if not _allowed(lat, lon, near):
                continue
            if state and state_of(lat, lon) not in (state, None):
                continue
            if near is not None and haversine_mi(near[0], near[1], lat, lon) > MAX_SPAN_MI:
                continue
            is_power = r.get("category") == "power" or r.get("type") in ("substation", "plant")
            return Match(
                query=name, lat=lat, lon=lon,
                confidence="medium" if is_power else "low",
                method="nominatim", matched_name=r.get("display_name", "")[:120],
                osm_id=f"{r.get('osm_type', '')}/{r.get('osm_id', '')}",
                score=0.0 if not is_power else MEDIUM,
            )
    return Match(query=name)
