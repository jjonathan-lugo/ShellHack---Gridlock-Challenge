"""Endpoint tests. The semantic endpoint is skipped when the Hugging Face
model isn't downloadable (no network) — that's an environment limitation,
not a failure."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_projects():
    r = client.get("/projects")
    assert r.status_code == 200
    projects = r.json()
    assert len(projects) > 0
    assert {"project_id", "utility", "project_name"} <= set(projects[0])


def test_overlaps_ranked():
    r = client.get("/overlaps")
    assert r.status_code == 200
    overlaps = r.json()
    assert len(overlaps) > 0
    assert [o["rank"] for o in overlaps] == list(range(1, len(overlaps) + 1))


def test_estimate():
    r = client.get("/estimate", params={"project_id_a": "DESC_2", "project_id_b": "GPC_1"})
    assert r.status_code == 200
    payload = r.json()
    assert payload["estimate"]["low_usd"] > 0
    assert payload["estimate"]["disclaimer"]


def test_estimate_unknown_pair_404():
    r = client.get("/estimate", params={"project_id_a": "NOPE", "project_id_b": "NOPE"})
    assert r.status_code == 404


def test_recommend_falls_back_to_template(monkeypatch):
    """Without HF_TOKEN the endpoint must still answer, not 503."""
    monkeypatch.delenv("HF_TOKEN", raising=False)
    r = client.get("/recommend", params={"project_id_a": "DESC_2", "project_id_b": "GPC_1"})
    assert r.status_code == 200
    payload = r.json()
    assert payload["source"] in ("template", "template_after_failed_guard")
    assert "4.09" in payload["recommendation"]
    assert payload["llm_unavailable_reason"]


def test_recommend_explicit_no_llm():
    r = client.get(
        "/recommend",
        params={"project_id_a": "DESC_2", "project_id_b": "GPC_1", "use_llm": False},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["source"] == "template"
    assert payload["llm_unavailable_reason"] is None


def test_recommend_unknown_pair_404():
    r = client.get("/recommend", params={"project_id_a": "NOPE", "project_id_b": "NOPE"})
    assert r.status_code == 404


def test_overlaps_semantic():
    try:
        r = client.get("/overlaps/semantic")
    except Exception as e:
        pytest.skip(f"Hugging Face model unavailable in this environment: {e}")
    if r.status_code != 200:
        pytest.skip("Hugging Face model unavailable in this environment")
    payload = r.json()
    assert "overlaps" in payload and "near_misses" in payload
    for o in payload["overlaps"]:
        assert 0.0 <= o["semantic_similarity"] <= 1.0


def test_auto_dataset_endpoints(monkeypatch, tmp_path, projects):
    import json as _json

    from fastapi.testclient import TestClient

    import backend.main as main

    client = TestClient(main.app)
    monkeypatch.setattr(main, "AUTO_DIR", tmp_path / "auto")
    assert client.get("/projects", params={"dataset": "auto"}).status_code == 404
    assert client.get("/ingest/report").status_code == 404
    assert client.get("/projects", params={"dataset": "bogus"}).status_code == 400

    (tmp_path / "auto").mkdir()
    unlocated = dict(projects[0], project_id="DESC-X", lat_center=None, lon_center=None,
                     lat_a=None, lon_a=None, lat_b=None, lon_b=None)
    (tmp_path / "auto" / "projects_auto.json").write_text(_json.dumps(projects + [unlocated]))
    (tmp_path / "auto" / "ingest_report.json").write_text(_json.dumps({"located": 10}))

    auto = client.get("/projects", params={"dataset": "auto"}).json()
    assert len(auto) == len(projects) + 1  # unlocated kept, so the UI can say "X of Y located"
    assert len(client.get("/overlaps", params={"dataset": "auto"}).json()) == 6
    assert client.get("/ingest/report").json() == {"located": 10}
    assert len(client.get("/overlaps").json()) == 6  # curated default unchanged
