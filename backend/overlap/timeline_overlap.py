"""Timeline overlap: the secondary signal, used alongside geographic overlap."""

from __future__ import annotations

from datetime import datetime


def _parse(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def time_gap_days(date_a: str | None, date_b: str | None) -> int | None:
    """Days between two projects' in-service dates, or None if either is unknown."""
    da, db = _parse(date_a), _parse(date_b)
    if da is None or db is None:
        return None
    return abs((da - db).days)
