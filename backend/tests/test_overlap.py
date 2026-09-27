"""The important test: our computed overlaps must match the hand-built
spreadsheet the team already validated. If this fails, either the source data
changed or the distance logic drifted — both worth knowing before a demo.
"""

import pytest

from backend.overlap.geo_overlap import (
    FLAG_THRESHOLD_MI,
    classify_tier,
    haversine_mi,
    project_center,
)
from backend.overlap.score import build_ranked_overlaps
from backend.overlap.timeline_overlap import time_gap_days


def test_matches_spreadsheet_pairs(utilities, spreadsheet_overlaps):
    desc, gpc = utilities
    computed = build_ranked_overlaps(desc, gpc)

    computed_pairs = {(o["project_id_a"], o["project_id_b"]) for o in computed}
    expected_pairs = {
        (o["project_id_a"], o["project_id_b"]) for o in spreadsheet_overlaps
    }
    assert computed_pairs == expected_pairs


def test_matches_spreadsheet_distances(utilities, spreadsheet_overlaps):
    desc, gpc = utilities
    computed = {
        (o["project_id_a"], o["project_id_b"]): o["distance_mi"]
        for o in build_ranked_overlaps(desc, gpc)
    }
    for row in spreadsheet_overlaps:
        key = (row["project_id_a"], row["project_id_b"])
        # Within 0.1 mi absorbs rounding differences between the two methods.
        assert computed[key] == pytest.approx(row["distance_mi"], abs=0.1)


def test_matches_spreadsheet_time_gaps(utilities, spreadsheet_overlaps):
    desc, gpc = utilities
    computed = {
        (o["project_id_a"], o["project_id_b"]): o["time_gap_days"]
        for o in build_ranked_overlaps(desc, gpc)
    }
    for row in spreadsheet_overlaps:
        key = (row["project_id_a"], row["project_id_b"])
        assert computed[key] == row["time_gap (day)"]


def test_ranked_by_distance_ascending(utilities):
    desc, gpc = utilities
    computed = build_ranked_overlaps(desc, gpc)
    distances = [o["distance_mi"] for o in computed]
    assert distances == sorted(distances)
    assert [o["rank"] for o in computed] == list(range(1, len(computed) + 1))


def test_nothing_beyond_threshold(utilities):
    desc, gpc = utilities
    for o in build_ranked_overlaps(desc, gpc):
        assert o["distance_mi"] <= FLAG_THRESHOLD_MI


def test_most_pairs_do_not_overlap(utilities):
    """The brief says most of the dataset should NOT overlap — finding the
    real matches is the point. Guards against an accidentally huge threshold."""
    desc, gpc = utilities
    total_pairs = len(desc) * len(gpc)
    flagged = len(build_ranked_overlaps(desc, gpc))
    assert flagged < total_pairs


class TestHaversine:
    def test_zero_distance(self):
        assert haversine_mi(33.5, -82.0, 33.5, -82.0) == pytest.approx(0, abs=1e-6)

    def test_symmetric(self):
        ab = haversine_mi(33.56, -82.05, 33.66, -82.19)
        ba = haversine_mi(33.66, -82.19, 33.56, -82.05)
        assert ab == pytest.approx(ba)

    def test_known_distance(self):
        # One degree of latitude is ~69 miles.
        assert haversine_mi(33.0, -82.0, 34.0, -82.0) == pytest.approx(69, abs=0.5)


class TestTierBoundaries:
    @pytest.mark.parametrize(
        "distance_mi,expected",
        [
            (0.0, "coordinate"),
            (0.5, "land"),  # ~0.8 km
            (3.0, "logistics"),  # ~4.8 km
            (15.0, "crew"),  # ~24 km
            (30.0, "none"),  # ~48 km, beyond 40 km
        ],
    )
    def test_tiers(self, distance_mi, expected):
        assert classify_tier(distance_mi).key == expected

    def test_every_tier_has_a_label(self):
        for mi in (0.0, 0.5, 3.0, 15.0, 30.0):
            assert classify_tier(mi).label


class TestProjectCenter:
    def test_midpoint_when_both_points_known(self):
        p = {"lat_a": 32.0, "lon_a": -81.0, "lat_b": 34.0, "lon_b": -83.0}
        assert project_center(p) == (33.0, -82.0)

    def test_single_point_a(self):
        p = {"lat_a": 32.0, "lon_a": -81.0, "lat_b": None, "lon_b": None}
        assert project_center(p) == (32.0, -81.0)

    def test_single_point_b(self):
        p = {"lat_a": None, "lon_a": None, "lat_b": 34.0, "lon_b": -83.0}
        assert project_center(p) == (34.0, -83.0)

    def test_none_when_ungeocoded(self):
        assert project_center({"lat_a": None, "lat_b": None}) is None


class TestTimeGap:
    def test_slash_format(self):
        assert time_gap_days("12/31/2024", "12/31/2024") == 0

    def test_iso_format(self):
        assert time_gap_days("2025-06-01", "2025-06-02") == 1

    def test_mixed_formats(self):
        assert time_gap_days("2024-12-31", "12/31/2024") == 0

    def test_absolute_value(self):
        assert time_gap_days("2020-01-01", "2021-01-01") == 366  # 2020 is a leap year

    def test_missing_date(self):
        assert time_gap_days(None, "2025-01-01") is None
        assert time_gap_days("2025-01-01", None) is None

    def test_unparseable_date(self):
        assert time_gap_days("sometime in 2025", "2025-01-01") is None
