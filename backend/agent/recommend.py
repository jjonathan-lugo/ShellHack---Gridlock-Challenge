"""Coordination-recommendation agent (add-on ideas #3 and #4).

Drafts a plain-English coordination suggestion for a ranked overlap.
Intentionally a *recommender*, not a decision-maker: per the team's own
notes, an expert human makes the final call.

Two modes:
  - LLM mode: pass a `call_llm` function (see llm_hf.py for the Hugging Face
    Inference API binding). Richer phrasing, but needs a token and network.
  - Template mode: pass nothing. Deterministic, offline, no dependencies —
    always available, so a demo never dies because an API is down.

Self-correction guard (add-on #4): an LLM draft's claimed distance must match
the raw overlap record before it's returned. If it doesn't after a retry, the
agent falls back to the template rather than shipping an unverified number.
That's the cheap, dependency-free way to stop hallucinated figures reaching
a planner.
"""

from __future__ import annotations

from typing import Callable, Optional

from backend.estimate.cost_impact import estimate_savings
from backend.overlap.geo_overlap import classify_tier

# Signature for a pluggable LLM: (prompt: str) -> str
LLMCall = Callable[[str], str]


PROMPT_TEMPLATE = """You are assisting utility planners, not deciding for them.
Given this flagged overlap between two planned construction projects, write a
2-3 sentence coordination recommendation. State the distance exactly as given
below — do not estimate, round differently, or invent any other figures. End by
noting that final coordination decisions rest with the utilities' own planners.

Overlap:
- Project A: {name_a} ({utility_a})
- Project B: {name_b} ({utility_b})
- Distance: {distance_mi} mi
- Coordination tier: {tier_label}
- In-service date gap: {time_gap_days} days
"""


TIER_ACTIONS = {
    "coordinate": (
        "These projects touch or cross, so coordination isn't optional: align outage "
        "windows and agree on crossing structures before either design is finalized."
    ),
    "land": (
        "At this range the two projects can share the corridor itself — right-of-way, "
        "access roads, and permitting are worth negotiating jointly rather than twice."
    ),
    "logistics": (
        "Close enough to share site logistics: a single laydown yard and consolidated "
        "material deliveries would serve both jobs."
    ),
    "crew": (
        "Within range to share crews and specialized equipment if the schedules are "
        "sequenced deliberately rather than left to chance."
    ),
}


def _tier_of(overlap: dict) -> str:
    return overlap.get("tier") or classify_tier(overlap["distance_mi"]).key


def _timing_note(time_gap_days: Optional[int]) -> str:
    if time_gap_days is None:
        return "In-service dates aren't both known, so the schedule fit needs checking by hand."
    years = time_gap_days / 365
    if time_gap_days <= 180:
        return (
            f"Their in-service dates are only {time_gap_days} days apart, so the build "
            "windows likely overlap — this is the strongest kind of candidate."
        )
    if years <= 2:
        return (
            f"Their in-service dates are about {years:.1f} years apart, so shared "
            "resourcing would need one side to shift phasing, but it's within reach."
        )
    return (
        f"Their in-service dates are roughly {years:.1f} years apart, so treat this as a "
        "geographic opportunity (shared corridor or access) rather than a shared-crew one."
    )


def template_recommendation(overlap: dict) -> str:
    """Deterministic, offline recommendation. No LLM, no network, no token."""
    tier = _tier_of(overlap)
    name_a = overlap.get("project_name_a", overlap.get("project_id_a", "Project A"))
    name_b = overlap.get("project_name_b", overlap.get("project_id_b", "Project B"))
    distance = overlap.get("distance_mi")

    parts = [
        f"{name_a} ({overlap.get('utility_a', 'Utility A')}) and {name_b} "
        f"({overlap.get('utility_b', 'Utility B')}) are {distance} mi apart.",
        TIER_ACTIONS.get(tier, "Worth a planner's review for shared resourcing."),
        _timing_note(overlap.get("time_gap_days")),
    ]

    estimate = estimate_savings(overlap)
    if estimate is not None:
        parts.append(
            f"Rough order of magnitude: ${round(estimate.low_usd / 1000)}k–"
            f"${round(estimate.high_usd / 1000)}k from {estimate.basis} "
            "(illustrative assumptions, not an engineering estimate)."
        )

    parts.append("Final coordination decisions rest with the utilities' own planners.")
    return " ".join(parts)


def _distance_is_faithful(draft: str, overlap: dict) -> bool:
    """Hallucination guard: the exact distance figure must appear in the draft."""
    return str(overlap.get("distance_mi")) in draft


def recommend(
    overlap: dict,
    call_llm: Optional[LLMCall] = None,
    max_retries: int = 1,
) -> dict:
    """Return {"recommendation", "source", "guard"}.

    source: "llm" (a draft that passed the fact-check), "template" (no LLM
    configured), or "template_after_failed_guard" (the LLM failed or never
    produced a draft with the right distance).

    guard: None in template mode; otherwise what the fact-check did —
    {"checked": "distance", "expected": "5.65", "rejected_drafts": [...],
     "error": str | None} — so a UI can show a hallucination being caught
    (and, when a retry fixes it, the agent correcting itself).
    """
    if call_llm is None:
        return {"recommendation": template_recommendation(overlap), "source": "template", "guard": None}

    prompt = PROMPT_TEMPLATE.format(
        name_a=overlap.get("project_name_a"),
        utility_a=overlap.get("utility_a"),
        name_b=overlap.get("project_name_b"),
        utility_b=overlap.get("utility_b"),
        distance_mi=overlap.get("distance_mi"),
        tier_label=overlap.get("tier_label") or classify_tier(overlap["distance_mi"]).label,
        time_gap_days=overlap.get("time_gap_days"),
    )
    guard = {"checked": "distance", "expected": str(overlap.get("distance_mi")), "rejected_drafts": [], "error": None}

    def fallback():
        return {
            "recommendation": template_recommendation(overlap),
            "source": "template_after_failed_guard",
            "guard": guard,
        }

    try:
        draft = call_llm(prompt)
    except Exception as e:
        # Any transport/model failure falls back rather than erroring out.
        guard["error"] = f"{type(e).__name__}: {e}"[:300]
        return fallback()

    attempts = 0
    while not _distance_is_faithful(draft, overlap):
        guard["rejected_drafts"].append(draft.strip())
        if attempts >= max_retries:
            return fallback()
        attempts += 1
        try:
            draft = call_llm(
                prompt
                + "\n\nYour previous draft misstated or omitted the distance. Redo it, "
                "using the exact figure given above."
            )
        except Exception as e:
            guard["error"] = f"{type(e).__name__}: {e}"[:300]
            return fallback()

    return {"recommendation": draft.strip(), "source": "llm", "guard": guard}
