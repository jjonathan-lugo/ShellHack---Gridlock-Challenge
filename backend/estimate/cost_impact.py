"""Rough cost/impact estimate for a flagged overlap (the challenge's bonus item).

Mirrors frontend/src/lib/cost.js and app/app.js so every surface quotes the
same figures. These are directional planning assumptions, NOT engineering
estimates — the point is to show the shape of the savings, not to price a job.
Swap ASSUMPTIONS for real utility cost data before anyone acts on a number.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from backend.overlap.geo_overlap import classify_tier

ASSUMPTIONS = {
    # Standing up a laydown yard / site mobilization for a single project.
    "yard_setup_low": 120_000,
    "yard_setup_high": 180_000,
    # Share of one project's setup avoidable when a nearby project shares it.
    "share_fraction_low": 0.40,
    "share_fraction_high": 0.60,
    # Acquiring/clearing right-of-way and access roads, per project.
    "row_low": 260_000,
    "row_high": 420_000,
    "row_share_fraction": 0.35,
    # Typical laydown yard footprint, acres.
    "yard_acres": 5,
    # Mobilizing a line crew to a remote site.
    "crew_mob_low": 40_000,
    "crew_mob_high": 75_000,
    "crew_share_fraction": 0.25,
}


@dataclass
class CostEstimate:
    tier: str
    low_usd: float
    high_usd: float
    basis: str
    detail: str
    assumptions: str
    disclaimer: str = (
        "Illustrative only — a directional planning figure, not an engineering "
        "estimate. Replace the built-in assumptions with real utility cost data "
        "before relying on it."
    )

    def to_dict(self) -> dict:
        return asdict(self)


def _k(value: float) -> str:
    return f"${round(value / 1000)}k"


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def estimate_savings(overlap: dict) -> CostEstimate | None:
    """Estimate the shared-resource savings for one flagged overlap.

    The tier decides what can realistically be shared: at touching/land range
    it's the corridor itself, at logistics range it's the laydown yard, at
    crew range it's mobilization. Returns None for pairs below the threshold.
    """
    tier = overlap.get("tier") or classify_tier(overlap["distance_mi"]).key
    a = ASSUMPTIONS

    if tier in ("coordinate", "land"):
        return CostEstimate(
            tier=tier,
            low_usd=a["row_low"] * a["row_share_fraction"],
            high_usd=a["row_high"] * a["row_share_fraction"],
            basis="shared right-of-way, access roads, and permitting",
            detail=(
                "At this distance the two projects can plausibly share the access "
                f"corridor itself rather than each clearing and permitting their own — "
                f"roughly {a['yard_acres']} acres of duplicated land use avoided."
            ),
            assumptions=(
                f"Assumes {_k(a['row_low'])}–{_k(a['row_high'])} per project for ROW "
                f"acquisition/clearing and access roads, with ~{_pct(a['row_share_fraction'])} "
                "avoidable when shared."
            ),
        )

    if tier == "logistics":
        return CostEstimate(
            tier=tier,
            low_usd=a["yard_setup_low"] * a["share_fraction_low"],
            high_usd=a["yard_setup_high"] * a["share_fraction_high"],
            basis="one shared laydown yard / site mobilization instead of two",
            detail=(
                "Close enough to run deliveries and material staging out of a single "
                f"~{a['yard_acres']}-acre yard rather than each utility standing up its own."
            ),
            assumptions=(
                f"Assumes a {_k(a['yard_setup_low'])}–{_k(a['yard_setup_high'])} standalone "
                f"laydown-yard setup per project, with {_pct(a['share_fraction_low'])}–"
                f"{_pct(a['share_fraction_high'])} of one project's cost avoidable when shared."
            ),
        )

    if tier == "crew":
        return CostEstimate(
            tier=tier,
            low_usd=a["crew_mob_low"] * a["crew_share_fraction"],
            high_usd=a["crew_mob_high"] * a["crew_share_fraction"],
            basis="shared crew and specialized equipment mobilization",
            detail=(
                "Too far apart to share a site, but within range to sequence the same "
                "line crews and specialized equipment across both jobs instead of "
                "mobilizing twice."
            ),
            assumptions=(
                f"Assumes {_k(a['crew_mob_low'])}–{_k(a['crew_mob_high'])} per crew/equipment "
                f"mobilization, with ~{_pct(a['crew_share_fraction'])} avoidable through "
                "shared scheduling."
            ),
        )

    return None
