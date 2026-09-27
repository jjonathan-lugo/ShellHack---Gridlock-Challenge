"""Geographic overlap detection.

Mirrors the logic already baked into data/Projects_Overlaps.xlsx and
app/app.js, so the two stay in sync as new project data comes in
(see the "make it autonomous" add-on idea).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MI_TO_KM = 1.60934
FLAG_THRESHOLD_MI = 25  # per the challenge brief: >25 mi apart = ignore


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in miles."""
    r_mi = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r_mi * math.asin(math.sqrt(a))


@dataclass
class Tier:
    key: str
    label: str


def classify_tier(distance_mi: float) -> Tier:
    """Bucket a flagged overlap by how much utilities could realistically share.

    Bands come from the project notes: touching/crossing needs full
    coordination; under 1.6km, land itself can be shared; under 8km, site
    logistics; under 40km, crew & equipment.
    """
    km = distance_mi * MI_TO_KM
    if km < 0.1:
        return Tier("coordinate", "Must coordinate (outage timing / crossing structure)")
    if km < 1.6:
        return Tier("land", "Can share land itself (ROW, access roads, permits)")
    if km < 8:
        return Tier("logistics", "Can share site logistics (laydown yards, deliveries)")
    if km < 40:
        return Tier("crew", "Can share crew & equipment")
    return Tier("none", "Below coordination threshold")


def project_center(project: dict) -> tuple[float, float] | None:
    """A project's center is the midpoint of its two named sub-points,
    or its single known point if only one is located."""
    lat_a, lon_a = project.get("lat_a"), project.get("lon_a")
    lat_b, lon_b = project.get("lat_b"), project.get("lon_b")
    if lat_a is not None and lat_b is not None:
        return (lat_a + lat_b) / 2, (lon_a + lon_b) / 2
    if lat_a is not None:
        return lat_a, lon_a
    if lat_b is not None:
        return lat_b, lon_b
    return None


def find_geo_overlaps(projects_a: list[dict], projects_b: list[dict]) -> list[dict]:
    """All cross-utility project pairs within FLAG_THRESHOLD_MI, with distance + tier."""
    results = []
    for pa in projects_a:
        ca = project_center(pa)
        if ca is None:
            continue
        for pb in projects_b:
            cb = project_center(pb)
            if cb is None:
                continue
            dist = haversine_mi(*ca, *cb)
            if dist <= FLAG_THRESHOLD_MI:
                tier = classify_tier(dist)
                results.append(
                    {
                        "project_id_a": pa["project_id"],
                        "project_id_b": pb["project_id"],
                        "distance_mi": round(dist, 2),
                        "tier": tier.key,
                        "tier_label": tier.label,
                    }
                )
    return results
