"""Semantic project matching using a Hugging Face sentence-transformer.

Supplements the geographic/timeline overlap signals with a text-similarity
score between project names/descriptions. Two uses:

1. Enrich already-flagged overlaps with a confidence signal — a pair that's
   both close *and* named similarly (e.g. both mention "Thurmond Dam") is a
   stronger coordination candidate than one that's merely close.
2. Surface near-misses: pairs with high name/description similarity that
   weren't geographically flagged, worth a human glance in case a geocoded
   point is slightly off.

Requires `sentence-transformers` (downloads a small model, ~90MB, from the
Hugging Face Hub on first use — needs network access once; cached after).
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def _project_text(project: dict) -> str:
    """What we embed: the project name plus both named sub-points, since
    utility naming conventions often repeat a shared facility's name
    (e.g. "Thurmond Sub" / "Thurmond Dam")."""
    parts = [project.get("project_name") or "", project.get("name_a") or "", project.get("name_b") or ""]
    return " ".join(p for p in parts if p).strip()


def semantic_similarity_matrix(projects_a: list[dict], projects_b: list[dict]) -> dict:
    """Cosine similarity between every A project's text and every B project's text.

    Returns {(project_id_a, project_id_b): similarity in [0, 1]}.
    """
    from sentence_transformers import util

    model = _get_model()
    texts_a = [_project_text(p) for p in projects_a]
    texts_b = [_project_text(p) for p in projects_b]

    emb_a = model.encode(texts_a, convert_to_tensor=True)
    emb_b = model.encode(texts_b, convert_to_tensor=True)
    sims = util.cos_sim(emb_a, emb_b)

    result = {}
    for i, pa in enumerate(projects_a):
        for j, pb in enumerate(projects_b):
            result[(pa["project_id"], pb["project_id"])] = float(sims[i][j])
    return result


def enrich_with_semantic_similarity(overlaps: list[dict], sim_matrix: dict) -> list[dict]:
    """Attach a semantic_similarity score to each already geo-flagged overlap, in place."""
    for o in overlaps:
        key = (o["project_id_a"], o["project_id_b"])
        o["semantic_similarity"] = round(sim_matrix.get(key, 0.0), 3)
    return overlaps


def find_semantic_near_misses(sim_matrix: dict, overlaps: list[dict], threshold: float = 0.55) -> list[dict]:
    """Pairs with high name/description similarity that weren't geographically
    flagged. Not a confirmed overlap — a hint that it's worth a second look."""
    flagged = {(o["project_id_a"], o["project_id_b"]) for o in overlaps}
    return sorted(
        (
            {"project_id_a": a, "project_id_b": b, "semantic_similarity": round(score, 3)}
            for (a, b), score in sim_matrix.items()
            if score >= threshold and (a, b) not in flagged
        ),
        key=lambda r: -r["semantic_similarity"],
    )
