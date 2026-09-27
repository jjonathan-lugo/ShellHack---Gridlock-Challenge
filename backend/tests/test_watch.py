"""Autonomous re-computation: spreadsheet export + overlap recompute + watcher."""

import json
import os
import shutil

import pytest

from backend.ingest import xlsx_export
from backend.ingest.watch import Watcher, refresh_weather

from .conftest import DATA_DIR, REPO_ROOT

XLSX = REPO_ROOT / "data" / "Projects_Overlaps.xlsx"
needs_xlsx = pytest.mark.skipif(not XLSX.exists(), reason="Projects_Overlaps.xlsx not in data/")


@needs_xlsx
def test_export_is_idempotent_with_committed_json(tmp_path):
    """Re-exporting the workbook reproduces the committed JSON byte for byte,
    so the watcher can rebuild freely without churning the data."""
    out = xlsx_export.export_and_recompute(XLSX, tmp_path, log=lambda *_: None)
    assert out["notes"] == []
    for name in ("projects.json", "overlaps.json"):
        assert (tmp_path / name).read_text() == (DATA_DIR / name).read_text()


def test_recompute_flags_new_and_stale_overlaps(projects, spreadsheet_overlaps):
    moved = [dict(p) for p in projects]
    # Move GPC_4 (south Georgia) right next to DESC_4 (Charleston) -> a new overlap.
    g4 = next(p for p in moved if p["project_id"] == "GPC_4")
    d4 = next(p for p in moved if p["project_id"] == "DESC_4")
    for k in ("lat_a", "lat_b", "lat_center"):
        g4[k] = d4["lat_center"] + 0.01
    for k in ("lon_a", "lon_b", "lon_center"):
        g4[k] = d4["lon_center"]
    # And push GPC_1 far away -> its overlaps disappear.
    g1 = next(p for p in moved if p["project_id"] == "GPC_1")
    for k in ("lat_a", "lat_b", "lat_center"):
        g1[k] = 30.5

    computed = xlsx_export.recompute_overlaps(moved)
    notes = xlsx_export.diff_overlap_tables(computed, spreadsheet_overlaps)
    assert any("new overlap" in n and "DESC_4 / GPC_4" in n for n in notes)
    assert sum("no longer within 25 mi" in n for n in notes) == 2  # OVL_1, OVL_4
    assert [o["overlap_id"] for o in computed] == [f"OVL_{i}" for i in range(1, len(computed) + 1)]


@needs_xlsx
def test_watcher_rebuilds_only_on_change(tmp_path):
    xlsx = tmp_path / "Projects_Overlaps.xlsx"
    shutil.copy(XLSX, xlsx)
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    processed = tmp_path / "processed"
    processed.mkdir()
    pipeline_runs, logs = [], []

    def make():
        return Watcher(xlsx=xlsx, pdfs=[pdf], processed=processed, state_file=tmp_path / "state.json",
                       weather=False, log=logs.append, run_pipeline=lambda: pipeline_runs.append(1))

    w = make()
    assert w.tick() == ["xlsx"]  # first start: spreadsheet exported, PDFs baselined
    assert pipeline_runs == []
    assert any("tip: run" in line for line in logs)
    assert json.loads((processed / "overlaps.json").read_text())[0]["overlap_id"] == "OVL_1"
    assert w.tick() == []  # nothing changed

    st = xlsx.stat()
    os.utime(xlsx, (st.st_atime, st.st_mtime + 10))
    assert w.tick() == ["xlsx"]

    st = pdf.stat()
    os.utime(pdf, (st.st_atime, st.st_mtime + 10))
    assert w.tick() == ["pdfs"] and pipeline_runs == [1]

    # State persists across restarts: a new watcher has nothing to do.
    assert make().tick() == []


def test_refresh_weather_fetches_only_missing(tmp_path, projects, monkeypatch):
    import backend.weather.fetch as fetch

    from .test_weather import synthetic_daily

    calls = []
    real = fetch.build_climatology_cache

    def fake_cache(missing, **_):
        calls.append([p["project_id"] for p in missing])
        return real(missing, fetch=lambda la, lo: synthetic_daily(seed=1), pause=0)

    monkeypatch.setattr(fetch, "build_climatology_cache", fake_cache)
    projects_path = tmp_path / "projects.json"
    projects_path.write_text(json.dumps(projects))
    cache_path = tmp_path / "weather.json"

    located = [p["project_id"] for p in projects if p.get("lat_center") is not None]
    assert refresh_weather(projects_path, cache_path, log=lambda *_: None) == len(located)
    assert refresh_weather(projects_path, cache_path, log=lambda *_: None) == 0  # all cached now

    extra = dict(projects[0], project_id="DESC_NEW")
    projects_path.write_text(json.dumps(projects + [extra]))
    assert refresh_weather(projects_path, cache_path, log=lambda *_: None) == 1
    assert calls[-1] == ["DESC_NEW"]
    assert "DESC_NEW" in json.loads(cache_path.read_text())["projects"]
