"""Combine geographic (primary) and timeline (secondary) signals into a
ranked list of coordination opportunities."""

from __future__ import annotations

from .geo_overlap import find_geo_overlaps
from .timeline_overlap import time_gap_days


def build_ranked_overlaps(projects_a: list[dict], projects_b: list[dict]) -> list[dict]:
    """Full pipeline: geo-flag every cross-utility pair, attach the timeline
    gap as secondary context, and rank by distance then time gap."""
    by_id = {p["project_id"]: p for p in [*projects_a, *projects_b]}

    overlaps = find_geo_overlaps(projects_a, projects_b)
    for o in overlaps:
        pa, pb = by_id[o["project_id_a"]], by_id[o["project_id_b"]]
        o["time_gap_days"] = time_gap_days(pa.get("in_service_date"), pb.get("in_service_date"))
        o["project_name_a"] = pa.get("project_name")
        o["project_name_b"] = pb.get("project_name")
        o["utility_a"] = pa.get("utility")
        o["utility_b"] = pb.get("utility")

    overlaps.sort(key=lambda o: (o["distance_mi"], o["time_gap_days"] if o["time_gap_days"] is not None else float("inf")))
    for i, o in enumerate(overlaps, start=1):
        o["rank"] = i
    return overlaps
