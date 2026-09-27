"""FastAPI backend — optional layer on top of the static app/ site.

The app currently ships as a static Leaflet page reading the pre-exported
JSON in data/processed/. This backend exists for the "make it autonomous"
add-on: point it at fresh project data and it recomputes overlaps on the
fly instead of requiring a manual re-export.

Run with:  uvicorn backend.main:app --reload
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.overlap.score import build_ranked_overlaps

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"

app = FastAPI(title="Gridlock API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


AUTO_DIR = DATA_DIR / "auto"


def _load_projects(dataset: str = "curated") -> list[dict]:
    """curated = the hand-geocoded spreadsheet export; auto = the PDF ingest
    pipeline's output (python3 -m backend.ingest.pipeline)."""
    if dataset == "auto":
        path = AUTO_DIR / "projects_auto.json"
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="No auto dataset yet. Run `python3 -m backend.ingest.pipeline` first.",
            )
        return json.loads(path.read_text())
    if dataset != "curated":
        raise HTTPException(status_code=400, detail="dataset must be 'curated' or 'auto'")
    with open(DATA_DIR / "projects.json") as f:
        return json.load(f)


def _split_utilities(projects: list[dict]) -> tuple[list[dict], list[dict]]:
    a = [p for p in projects if "Dominion" in p["utility"]]
    b = [p for p in projects if p["utility"] not in {pa["utility"] for pa in a}]
    return a, b


@app.get("/projects")
def get_projects(dataset: str = "curated"):
    return _load_projects(dataset)


@app.get("/overlaps")
def get_overlaps(dataset: str = "curated"):
    """Recomputes overlaps live from the project table rather than serving the
    static overlaps.json export — this is the "autonomous" path."""
    a, b = _split_utilities(_load_projects(dataset))
    return build_ranked_overlaps(a, b)


@app.get("/ingest/report")
def get_ingest_report():
    """Coverage/confidence summary from the last PDF ingest run, including the
    check against the hand-geocoded spreadsheet."""
    path = AUTO_DIR / "ingest_report.json"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="No ingest report yet. Run `python3 -m backend.ingest.pipeline` first.",
        )
    return json.loads(path.read_text())


@app.get("/overlaps/semantic")
def get_overlaps_semantic():
    """Same as /overlaps, but enriched with a Hugging Face sentence-transformer
    similarity score on each pair's name/description text, plus a list of
    "near-miss" pairs that read as related but weren't geographically flagged
    (worth a human glance — could mean a geocoded point is slightly off).

    First call downloads the model (~90MB) from the Hugging Face Hub and is
    slow; subsequent calls use the cached model and are fast.
    """
    from backend.match.semantic_match import (
        enrich_with_semantic_similarity,
        find_semantic_near_misses,
        semantic_similarity_matrix,
    )

    a, b = _split_utilities(_load_projects())
    ranked = build_ranked_overlaps(a, b)
    sim_matrix = semantic_similarity_matrix(a, b)
    enriched = enrich_with_semantic_similarity(ranked, sim_matrix)
    near_misses = find_semantic_near_misses(sim_matrix, ranked)
    return {"overlaps": enriched, "near_misses": near_misses}


def _find_overlap(project_id_a: str, project_id_b: str) -> dict:
    a, b = _split_utilities(_load_projects())
    ranked = build_ranked_overlaps(a, b)
    match = next(
        (
            o
            for o in ranked
            if o["project_id_a"] == project_id_a and o["project_id_b"] == project_id_b
        ),
        None,
    )
    if match is None:
        raise HTTPException(
            status_code=404, detail="No flagged overlap for that project pair"
        )
    return match


@app.get("/estimate")
def get_estimate(project_id_a: str, project_id_b: str):
    """Rough shared-resource cost/impact estimate for one flagged overlap
    (the challenge's bonus item). Directional only — see the disclaimer in
    the response and backend/estimate/cost_impact.py for the assumptions."""
    from backend.estimate.cost_impact import estimate_savings

    match = _find_overlap(project_id_a, project_id_b)
    estimate = estimate_savings(match)
    return {
        "overlap": match,
        "estimate": estimate.to_dict() if estimate else None,
    }


@app.get("/recommend")
def get_recommendation(project_id_a: str, project_id_b: str, use_llm: bool = True):
    """Drafts a plain-English coordination recommendation for one flagged overlap.

    Tries a Hugging Face-hosted LLM when `use_llm` is true and HF_TOKEN is set,
    with a hallucination guard on the distance figure; otherwise (or if the
    model call fails) returns the deterministic offline template. The response's
    `source` field says which path produced it, so a demo never breaks just
    because a token is missing or an endpoint is cold.

    This is a recommender only: per the team's own notes, final coordination
    decisions rest with the utilities' planners.
    """
    from backend.agent.recommend import recommend

    match = _find_overlap(project_id_a, project_id_b)

    call_llm = None
    llm_unavailable_reason = None
    if use_llm:
        try:
            from backend.agent.llm_hf import make_hf_llm_call

            call_llm = make_hf_llm_call()
        except RuntimeError as e:
            llm_unavailable_reason = str(e)

    result = recommend(match, call_llm)
    return {
        "overlap": match,
        **result,
        "llm_unavailable_reason": llm_unavailable_reason,
    }


WEATHER_CACHE = DATA_DIR / "weather_climatology.json"


def _load_weather_cache() -> dict | None:
    if not WEATHER_CACHE.exists():
        return None
    with open(WEATHER_CACHE) as f:
        return json.load(f)


def _monthly_for(project: dict, cache: dict | None) -> list[dict]:
    """Cached climatology for a project, or a live Open-Meteo fetch if uncached."""
    if cache and project["project_id"] in cache.get("projects", {}):
        return cache["projects"][project["project_id"]]["monthly"]
    from backend.weather.climatology import monthly_climatology
    from backend.weather.fetch import fetch_daily

    if project.get("lat_center") is None:
        return []
    try:
        return monthly_climatology(fetch_daily(project["lat_center"], project["lon_center"]))
    except RuntimeError as e:
        raise HTTPException(
            status_code=503,
            detail=f"No cached weather and Open-Meteo is unreachable ({e}). "
            "Run `python3 -m backend.weather.fetch` while online.",
        )


@app.get("/weather")
def get_weather():
    """Cached per-project monthly climatology (lost-work-day statistics)."""
    cache = _load_weather_cache()
    if cache is None:
        raise HTTPException(
            status_code=404,
            detail="No weather cache yet. Run `python3 -m backend.weather.fetch` while online.",
        )
    return cache


@app.get("/weather/overlap")
def get_overlap_weather(project_id_a: str, project_id_b: str):
    """Build-window weather risk for a project pair: each side's expected
    weather-lost days, high-risk months, best 3-month stretch, and the months
    where both crews would be in the field at once."""
    from backend.weather.risk import overlap_weather

    by_id = {p["project_id"]: p for p in _load_projects()}
    if project_id_a not in by_id or project_id_b not in by_id:
        raise HTTPException(status_code=404, detail="Unknown project id")
    pa, pb = by_id[project_id_a], by_id[project_id_b]
    cache = _load_weather_cache()
    return overlap_weather(_monthly_for(pa, cache), _monthly_for(pb, cache), pa, pb)


@app.get("/health")
def health():
    return {"status": "ok"}
