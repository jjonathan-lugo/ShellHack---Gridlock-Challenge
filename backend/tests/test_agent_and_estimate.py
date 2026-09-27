"""Tests for the cost estimate and the recommendation agent, including the
hallucination guard. None of these touch the network — the LLM is faked."""

import pytest

from backend.agent.recommend import recommend, template_recommendation
from backend.estimate.cost_impact import estimate_savings


@pytest.fixture
def overlap():
    return {
        "project_id_a": "DESC_2",
        "project_id_b": "GPC_1",
        "project_name_a": "Hooks - Thurmond 115 kV Tie: Rebuild",
        "project_name_b": "EVANS PRIMARY - THURMOND DAM (USA) #5 115KV REBUILD",
        "utility_a": "Dominion Energy South Carolina",
        "utility_b": "Georgia Power",
        "distance_mi": 4.09,
        "tier": "logistics",
        "tier_label": "Can share site logistics (laydown yards, deliveries)",
        "time_gap_days": 3074,
    }


class TestCostEstimate:
    def test_logistics_tier_estimate(self, overlap):
        est = estimate_savings(overlap)
        assert est is not None
        assert est.tier == "logistics"
        assert 0 < est.low_usd < est.high_usd
        assert "laydown" in est.basis.lower()
        assert est.disclaimer

    def test_land_tier_is_larger_than_crew_tier(self, overlap):
        land = estimate_savings({**overlap, "tier": "land"})
        crew = estimate_savings({**overlap, "tier": "crew"})
        # Sharing the corridor itself should be worth more than sharing crews.
        assert land.high_usd > crew.high_usd

    def test_no_estimate_below_threshold(self, overlap):
        assert estimate_savings({**overlap, "tier": "none"}) is None

    def test_tier_inferred_from_distance_when_absent(self, overlap):
        without_tier = {k: v for k, v in overlap.items() if k != "tier"}
        assert estimate_savings(without_tier).tier == "logistics"

    def test_serializable(self, overlap):
        assert isinstance(estimate_savings(overlap).to_dict(), dict)


class TestTemplateRecommendation:
    def test_contains_exact_distance(self, overlap):
        assert "4.09" in template_recommendation(overlap)

    def test_names_both_projects(self, overlap):
        text = template_recommendation(overlap)
        assert overlap["project_name_a"] in text
        assert overlap["project_name_b"] in text

    def test_defers_to_human_planners(self, overlap):
        assert "planners" in template_recommendation(overlap).lower()

    def test_timing_note_reflects_a_close_schedule(self, overlap):
        text = template_recommendation({**overlap, "time_gap_days": 30})
        assert "30 days apart" in text

    def test_handles_unknown_schedule(self, overlap):
        text = template_recommendation({**overlap, "time_gap_days": None})
        assert "by hand" in text


class TestRecommendAgent:
    def test_template_mode_without_llm(self, overlap):
        result = recommend(overlap)
        assert result["source"] == "template"
        assert "4.09" in result["recommendation"]

    def test_uses_faithful_llm_draft(self, overlap):
        def good_llm(prompt):
            return "These projects sit 4.09 mi apart; share a laydown yard. Planners decide."

        result = recommend(overlap, good_llm)
        assert result["source"] == "llm"
        assert "4.09" in result["recommendation"]

    def test_retries_then_accepts_corrected_draft(self, overlap):
        calls = []

        def flaky_llm(prompt):
            calls.append(prompt)
            if len(calls) == 1:
                return "These projects sit about 5 miles apart."  # wrong figure
            return "Corrected: they sit 4.09 mi apart. Planners decide."

        result = recommend(overlap, flaky_llm)
        assert len(calls) == 2, "should have retried once"
        assert result["source"] == "llm"

    def test_falls_back_when_guard_keeps_failing(self, overlap):
        def hallucinating_llm(prompt):
            return "These projects sit about 12 miles apart, give or take."

        result = recommend(overlap, hallucinating_llm)
        assert result["source"] == "template_after_failed_guard"
        # The unverified figure must not reach the caller.
        assert "12 miles" not in result["recommendation"]
        assert "4.09" in result["recommendation"]

    def test_falls_back_when_llm_raises(self, overlap):
        def broken_llm(prompt):
            raise ConnectionError("HF endpoint cold")

        result = recommend(overlap, broken_llm)
        assert result["source"] == "template_after_failed_guard"
        assert "4.09" in result["recommendation"]
