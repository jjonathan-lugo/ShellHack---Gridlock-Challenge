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

from fastapi import FastAPI
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


def _load_projects() -> list[dict]:
    with open(DATA_DIR / "projects.json") as f:
        return json.load(f)


@app.get("/projects")
def get_projects():
    return _load_projects()


@app.get("/overlaps")
def get_overlaps():
    """Recomputes overlaps live from projects.json rather than serving the
    static overlaps.json export — this is the "autonomous" path."""
    projects = _load_projects()
    a = [p for p in projects if "Dominion" in p["utility"]]
    b = [p for p in projects if p["utility"] not in {pa["utility"] for pa in a}]
    return build_ranked_overlaps(a, b)


@app.get("/health")
def health():
    return {"status": "ok"}
