"""Spreadsheet -> data/processed JSON, and overlaps recomputed from the projects.

    python3 -m backend.ingest.xlsx_export

Projects_Overlaps.xlsx is the hand-built source of truth. Its "projects"
sheet is written to projects.json; recompute_overlaps() then
rebuilds overlaps.json from those projects with the same haversine/tier code
the backend uses, so adding a row to the sheet is all it takes to update the
ranked list. The sheet's own "overlaps" tab is compared, not trusted blindly:
differences are reported so a stale hand-made overlap table gets noticed.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from backend.overlap.score import build_ranked_overlaps

REPO_ROOT = Path(__file__).resolve().parents[2]
XLSX = REPO_ROOT / "data" / "Projects_Overlaps.xlsx"
PROCESSED = REPO_ROOT / "data" / "processed"


def _cell(v):
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%Y-%m-%d")
    return v


def read_sheet(xlsx: Path, sheet: str) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    ws = wb[sheet]
    rows = ws.iter_rows(values_only=True)
    headers = list(next(rows))
    out = []
    for row in rows:
        if row[0] is None:
            continue
        out.append({h: _cell(v) for h, v in zip(headers, row) if h is not None})
    wb.close()
    return out


def recompute_overlaps(projects: list[dict]) -> list[dict]:
    """overlaps.json rows (spreadsheet export shape) computed from the projects."""
    desc = [p for p in projects if "Dominion" in p["utility"]]
    other = [p for p in projects if p not in desc]
    rows = []
    for o in build_ranked_overlaps(desc, other):
        rows.append(
            {
                "overlap_id": f"OVL_{o['rank']}",
                "distance_mi": round(o["distance_mi"], 2),
                "time_gap (day)": o["time_gap_days"],
                "utility_a": o["utility_a"],
                "project_id_a": o["project_id_a"],
                "project_name_a": o["project_name_a"],
                "utility_b": o["utility_b"],
                "project_id_b": o["project_id_b"],
                "project_name_b": o["project_name_b"],
            }
        )
    return rows


def diff_overlap_tables(computed: list[dict], sheet: list[dict], tol_mi: float = 0.1) -> list[str]:
    """Human-readable differences between the recomputed and hand-made tables."""
    key = lambda o: (o["project_id_a"], o["project_id_b"])  # noqa: E731
    c, s = {key(o): o for o in computed}, {key(o): o for o in sheet}
    notes = []
    for k in sorted(set(c) - set(s)):
        notes.append(f"new overlap not in the sheet's overlaps tab: {k[0]} / {k[1]} ({c[k]['distance_mi']} mi)")
    for k in sorted(set(s) - set(c)):
        notes.append(f"sheet lists {k[0]} / {k[1]} but they're no longer within 25 mi")
    for k in sorted(set(c) & set(s)):
        if abs(float(c[k]["distance_mi"]) - float(s[k]["distance_mi"])) > tol_mi:
            notes.append(f"{k[0]} / {k[1]}: sheet says {s[k]['distance_mi']} mi, coordinates give {c[k]['distance_mi']} mi")
    return notes


def export_and_recompute(xlsx: Path = XLSX, out_dir: Path = PROCESSED, log=print) -> dict:
    projects = read_sheet(xlsx, "projects")
    computed = recompute_overlaps(projects)
    try:
        notes = diff_overlap_tables(computed, read_sheet(xlsx, "overlaps"))
    except KeyError:
        notes = ["workbook has no 'overlaps' sheet; using recomputed overlaps only"]
    (out_dir / "projects.json").write_text(json.dumps(projects, indent=2))
    (out_dir / "overlaps.json").write_text(json.dumps(computed, indent=2))
    log(f"Exported {len(projects)} projects and {len(computed)} recomputed overlaps from {xlsx.name}")
    for n in notes:
        log(f"  note: {n}")
    return {"projects": projects, "overlaps": computed, "notes": notes}


if __name__ == "__main__":
    # python3 -m backend.ingest.xlsx_export
    export_and_recompute()
