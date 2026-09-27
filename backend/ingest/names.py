"""Project name -> named sub-points, and station-name normalization for matching.

Per the Sperry Tech guide, a project's center is the midpoint of its two named
sub-points (or the one point, if only one is known). Utility project titles
put those names up front, before the voltage and the work description:

    "Stevens Creek - Hooks 115kV/LR Plumb Branch 46kV Rebuilds"  -> Stevens Creek, Hooks
    "EVANS PRIMARY - THURMOND DAM (USA) #5 115KV REBUILD"        -> EVANS PRIMARY, THURMOND DAM
    "SAV: GOSHEN (SAV) - MCINTOSH 115KV LINE REBUILD"            -> GOSHEN, MCINTOSH
    "Edenwood Sub: #1 & #2 230-115kV Autobanks, Replace ..."     -> Edenwood
"""

from __future__ import annotations

import re

# Sponsor / program prefixes in the Georgia ITS table.
_PREFIX = re.compile(r"^\s*(?:(?:SAV|GTC|MEAG|DU)\s*:\s*|(?:CC|GRID)\s*-\s*)+", re.I)
# Transmission voltages in these filings (plus the "23O KV" typo in one GPC row).
_VOLTAGE = re.compile(r"\b(?:46|69|115|138|161|230|500|23O)(?![\d.])(?:\s*[-/]\s*[\d.]+)*\s*(?:K\s*V)?", re.I)
_PAREN = re.compile(r"\([^)]*\)")
_LINE_NO = re.compile(r"#\s*\d+\w*")
_SEPARATORS = re.compile(r"(\s*[-–—]\s*|\s+&\s+|\s+AND\s+|/)", re.I)

# Words that start the "what work is being done" part of a name.
WORK_WORDS = {
    "REBUILD", "REBUILDS", "REBLD", "RECONDUCTOR", "LINE", "LINES", "TL", "TIE", "TAP",
    "SUB", "SUBSTATION", "STATION", "SWITCHING", "SWITCH", "SWITCHYARD", "BUS", "BUSES",
    "BREAKER", "RELAY", "RELAYS", "CAPACITOR", "CAP", "REACTOR", "REACTORS", "STATCOM",
    "TRANSFORMER", "TRANSFORMERS", "XFMR", "AUTOBANK", "AUTOBANKS", "AUTO", "BANK",
    "UPGRADE", "UPGRADES", "MODERNIZATION", "REPLACEMENT", "REPLACE", "INSTALLATION",
    "INSTALL", "PROJECT", "AREA", "IMPROVEMENTS", "IMPROVEMENT", "NEW", "CONSTRUCT",
    "EQUIPMENT", "STRATEGIC", "SOLUTION", "SERIES", "SECOND", "2ND", "PROTECTIVE",
    "JUMPER", "JUMPERS", "LOOP", "TRANSMISSION", "CONVERSION", "REMOVAL", "NEEDS", "SYSTEM",
    "PANEL", "LIMITING", "SMART", "VALVE", "VALVES", "PARTIAL", "MODIFICATION",
    "EXPANSION", "FOLD", "SPDC", "DUAL", "LOW", "SIDE", "PARALLEL", "BUILD", "SECTION",
    "DISTRIBUTION", "ADD", "PHASE",
}


def _strip_work_words(segment: str) -> str:
    """Cut a segment at its first work word — unless the segment *starts* with
    one (e.g. "LINE CREEK" is a real station), in which case look past it."""
    tokens = segment.split()
    for i, tok in enumerate(tokens):
        if i > 0 and re.sub(r"[^A-Z0-9]", "", tok.upper()) in WORK_WORDS:
            tokens = tokens[:i]
            break
    if all(re.sub(r"[^A-Z0-9]", "", t.upper()) in WORK_WORDS for t in tokens):
        return ""
    return " ".join(tokens)


def _cut_at_work_words(s: str) -> str:
    """Cut the whole name at the first work word that continues a station name
    ("PLANT YATES BREAKER AND HALF STATION" -> "PLANT YATES"), but not at one
    that begins a new segment ("CLIFTONDALE - LINE CREEK" keeps LINE CREEK)."""
    parts = _SEPARATORS.split(s)
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # a separator
            out.append(part)
            continue
        tokens = part.split()
        for j, tok in enumerate(tokens):
            if j > 0 and re.sub(r"[^A-Z0-9]", "", tok.upper()) in WORK_WORDS:
                out.append(" ".join(tokens[:j]))
                return "".join(out)
        out.append(part)
    return "".join(out)


def sub_points(project_name: str) -> list[str]:
    """Named endpoints of a project: [a, b], [a], or [] if none can be found.
    With three or more (A - B - C), the first and last are the endpoints."""
    s = _PREFIX.sub("", project_name or "")
    s = s.split(":")[0]
    s = _PAREN.sub(" ", s)
    m = _VOLTAGE.search(s)
    if m:
        s = s[: m.start()]
    s = s.split(",")[0]
    s = _cut_at_work_words(s)

    points = []
    for seg in _SEPARATORS.split(s)[::2]:
        seg = _LINE_NO.sub(" ", seg)
        seg = re.sub(r"\s+", " ", seg).strip(" .-")
        seg = _strip_work_words(seg)
        if seg and not seg.isdigit() and seg.upper() not in {p.upper() for p in points}:
            points.append(seg)
    if len(points) > 2:
        points = [points[0], points[-1]]
    return points


# ---------------- normalization for matching ----------------

_ABBREV = {
    "PRI": "PRIMARY", "JCT": "JUNCTION", "FT": "FORT", "MT": "MOUNT", "RD": "ROAD",
    "N": "NORTH", "S": "SOUTH", "E": "EAST", "W": "WEST", "CR": "CREEK",
}
# Generic words that say "this is a substation" but not *which* one.
_GENERIC = {"SUB", "SUBSTATION", "SUBSTA", "SS", "STATION", "SWITCHING", "SWITCHYARD",
            "SWITCH", "PRIMARY", "PLANT", "THE", "TRANSMISSION", "DISTRIBUTION", "TAP",
            "KV", "SUBSTATIONS"}


def normalize_station(name: str) -> str:
    """Canonical form for comparing a project sub-point with an OSM feature name."""
    s = _PAREN.sub(" ", (name or "").upper())
    s = _LINE_NO.sub(" ", s)
    s = re.sub(r"\b\d+(?:\.\d+)?\s*KV\b", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    tokens = s.split()
    out = []
    for i, t in enumerate(tokens):
        if t == "ST":
            t = "SAINT" if i == 0 else "STREET"
        t = _ABBREV.get(t, t)
        if t in _GENERIC or t.isdigit():
            continue
        out.append(t)
    return " ".join(out)
