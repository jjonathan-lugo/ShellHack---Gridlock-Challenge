"""Stub for the AI recommendation agent (add-on idea #3/#4).

Drafts a plain-English coordination suggestion for a ranked overlap.
Intentionally a *recommender*, not a decision-maker: per the team's own
notes, an expert human should make the final call.

Self-correction guard (add-on #4): before returning a recommendation, the
draft's claimed distance/date figures are checked against the raw overlap
record. If they don't match, the agent is asked to redo it. This is a cheap
way to catch hallucinated numbers without a full agent framework.
"""

from __future__ import annotations

import re
from typing import Callable

# Plug in a real LLM call here (Anthropic, OpenAI, or a Hugging Face model).
# Signature: (prompt: str) -> str
LLMCall = Callable[[str], str]


PROMPT_TEMPLATE = """You are assisting utility planners, not deciding for them.
Given this flagged overlap between two planned construction projects, write a
2-3 sentence coordination recommendation. State the distance and tier
exactly as given below — do not estimate or round differently. End by noting
that final coordination decisions rest with the utilities' own planners.

Overlap:
- Project A: {name_a} ({utility_a})
- Project B: {name_b} ({utility_b})
- Distance: {distance_mi} mi
- Coordination tier: {tier_label}
- In-service date gap: {time_gap_days} days
"""


def _numbers_match(draft: str, overlap: dict) -> bool:
    """Cheap hallucination guard: the distance figure the model wrote must
    appear verbatim in the draft."""
    distance_str = str(overlap["distance_mi"])
    return distance_str in draft


def recommend(overlap: dict, call_llm: LLMCall, max_retries: int = 1) -> str:
    prompt = PROMPT_TEMPLATE.format(
        name_a=overlap.get("project_name_a"),
        utility_a=overlap.get("utility_a"),
        name_b=overlap.get("project_name_b"),
        utility_b=overlap.get("utility_b"),
        distance_mi=overlap.get("distance_mi"),
        tier_label=overlap.get("tier_label"),
        time_gap_days=overlap.get("time_gap_days"),
    )

    draft = call_llm(prompt)
    attempts = 0
    while not _numbers_match(draft, overlap) and attempts < max_retries:
        draft = call_llm(prompt + "\n\nYour previous draft misstated the distance. Redo it, using the exact figure given above.")
        attempts += 1

    if not _numbers_match(draft, overlap):
        # Fall back to a templated line rather than ship an unverified number.
        return (
            f"{overlap.get('project_name_a')} and {overlap.get('project_name_b')} are "
            f"{overlap.get('distance_mi')} mi apart ({overlap.get('tier_label')}). "
            "Recommend planners review for shared logistics. Final decision rests with utility planners."
        )
    return draft
