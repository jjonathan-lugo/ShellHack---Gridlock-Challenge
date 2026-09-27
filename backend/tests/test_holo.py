"""3D holographic view: the shared deck.gl scene builder (app/holo.js)."""

import json
import shutil
import subprocess

import pytest

from .conftest import REPO_ROOT


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_holo_scene_matches_dataset(tmp_path, projects, spreadsheet_overlaps):
    script = tmp_path / "run.js"
    script.write_text(f"""
require({json.dumps(str(REPO_ROOT / "app" / "holo.js"))});
const H = globalThis.GridlockHolo;
const projects = {json.dumps(projects)};
const overlaps = {json.dumps(spreadsheet_overlaps)};
const s = H.buildScene({{ projects, overlaps }});
const arc = s.arcs[0];
process.stdout.write(JSON.stringify({{
  nodes: s.nodes.length, spans: s.spans.length, arcs: s.arcs.length, pulses: s.pulses.length,
  grid: s.grid.length, arcIds: s.arcs.map(a => a.id),
  arcStart: arc.path[0], arcEnd: arc.path[arc.path.length - 1],
  arcPeak: Math.max(...arc.path.map(p => p[2])),
  counts: Object.fromEntries(s.nodes.map(n => [n.id, n.overlaps])),
  view: H.initialViewState(projects),
  tiers: overlaps.map(o => H.tierKey(o.distance_mi)),
}}));
""")
    out = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout)
    located = [p for p in projects if p.get("lat_center") is not None]
    spans = [p for p in projects if None not in (p.get("lat_a"), p.get("lat_b"))]

    assert out["nodes"] == len(located)
    assert out["spans"] == len(spans)
    assert out["arcs"] == len(spreadsheet_overlaps)
    assert out["pulses"] == 2 * len(spreadsheet_overlaps) + len(spans)
    assert out["grid"] > 10
    assert out["arcIds"] == [o["overlap_id"] for o in spreadsheet_overlaps]

    # Arcs start/end at the two project centers and rise in between.
    first = spreadsheet_overlaps[0]
    by_id = {p["project_id"]: p for p in projects}
    a, b = by_id[first["project_id_a"]], by_id[first["project_id_b"]]
    assert out["arcStart"][:2] == pytest.approx([a["lon_center"], a["lat_center"]])
    assert out["arcEnd"][:2] == pytest.approx([b["lon_center"], b["lat_center"]])
    assert out["arcPeak"] > 10000

    # Column height input = number of flagged overlaps per project.
    expected = {}
    for o in spreadsheet_overlaps:
        for pid in (o["project_id_a"], o["project_id_b"]):
            expected[pid] = expected.get(pid, 0) + 1
    assert {k: v for k, v in out["counts"].items() if v} == expected

    # Tier keys agree with the Python tiers used everywhere else.
    from backend.overlap.geo_overlap import classify_tier
    assert out["tiers"] == [classify_tier(o["distance_mi"]).key for o in spreadsheet_overlaps]
    assert out["view"]["pitch"] == 55
