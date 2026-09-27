"""The AI-recommendation panel: the browser's offline template (app/agent.js)
must say exactly what the backend's template says for every overlap the UI
lists, and /recommend must report what the fact-check caught."""

import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.agent.recommend import recommend, template_recommendation

from .conftest import REPO_ROOT

client = TestClient(main.app)
AUTO = REPO_ROOT / "data" / "processed" / "auto" / "overlaps_auto.json"


def _ui_rows():
    """(dataset, overlap row exactly as the UI loads it)."""
    rows = [("curated", o) for o in json.loads((REPO_ROOT / "data" / "processed" / "overlaps.json").read_text())]
    if AUTO.exists():
        rows += [("auto", o) for o in json.loads(AUTO.read_text())]
    return rows


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_js_template_matches_backend_on_every_listed_overlap(tmp_path):
    rows = _ui_rows()
    script = tmp_path / "t.js"
    script.write_text(
        f"const A = require({json.dumps(str(REPO_ROOT / 'app' / 'agent.js'))});\n"
        f"const rows = {json.dumps([o for _, o in rows])};\n"
        "console.log(JSON.stringify(rows.map((o) => A.templateRecommendation(o))));\n"
    )
    js = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout)
    for (dataset, row), js_text in zip(rows, js):
        backend_overlap = main._find_overlap(row["project_id_a"], row["project_id_b"], dataset)
        assert js_text == template_recommendation(backend_overlap), (dataset, row["project_id_a"], row["project_id_b"])


def test_guard_reports_a_caught_hallucination():
    o = main._find_overlap("DESC_3", "GPC_2")
    r = recommend(o, lambda prompt: "They are about 6 miles apart.")
    assert r["source"] == "template_after_failed_guard"
    assert r["guard"]["expected"] == "5.65"
    assert r["guard"]["rejected_drafts"] == ["They are about 6 miles apart."] * 2  # first try + one retry
    assert "6 miles" not in r["recommendation"] and "5.65" in r["recommendation"]


def test_guard_reports_self_correction():
    o = main._find_overlap("DESC_3", "GPC_2")
    drafts = iter(["Roughly 6 miles apart.", "They are 5.65 mi apart; share crews. Planners decide."])
    r = recommend(o, lambda prompt: next(drafts))
    assert r["source"] == "llm" and r["guard"]["rejected_drafts"] == ["Roughly 6 miles apart."]


def test_guard_reports_transport_errors():
    def down(prompt):
        raise ConnectionError("endpoint cold")

    r = recommend(main._find_overlap("DESC_3", "GPC_2"), down)
    assert r["source"] == "template_after_failed_guard" and "ConnectionError" in r["guard"]["error"]


def test_recommend_endpoint_serves_both_datasets_and_caches(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    main._RECOMMEND_CACHE.clear()
    r = client.get("/recommend", params={"project_id_a": "DESC_3", "project_id_b": "GPC_2"})
    assert r.status_code == 200 and r.json()["source"] == "template" and r.json()["guard"] is None
    assert main._RECOMMEND_CACHE  # remembered

    if AUTO.exists():
        row = json.loads(AUTO.read_text())[0]
        r = client.get("/recommend", params={"project_id_a": row["project_id_a"], "project_id_b": row["project_id_b"], "dataset": "auto"})
        assert r.status_code == 200 and str(row["distance_mi"]) in r.json()["recommendation"]


def test_recommend_does_not_cache_transport_errors(monkeypatch):
    import backend.agent.llm_hf as llm_hf

    main._RECOMMEND_CACHE.clear()
    calls = []

    def factory(*_a, **_k):
        def call(prompt):
            calls.append(1)
            raise ConnectionError("cold")
        return call

    monkeypatch.setattr(llm_hf, "make_hf_llm_call", factory)
    for _ in range(2):
        r = client.get("/recommend", params={"project_id_a": "DESC_3", "project_id_b": "GPC_2"})
        assert r.json()["source"] == "template_after_failed_guard"
    assert len(calls) == 2  # retried on the second request, not served from cache
    main._RECOMMEND_CACHE.clear()
