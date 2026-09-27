"""Build-window weather risk for a project, and for a flagged overlap pair.

Build window: the BUILD_WINDOW_MONTHS calendar months ending with the
in-service month (e.g. in-service 6/1/2033 -> Jul 2032 .. Jun 2033). That is a
planning assumption for a typical line rebuild, not a date from the filings.

Risk level per month, from the share of days likely lost to weather:
  low       < 15%
  moderate  15% - 30%
  high      >= 30%

Mirrored exactly in app/weather.js and frontend/src/lib/weather.js.
"""

from __future__ import annotations

from backend.overlap.timeline_overlap import _parse
from backend.weather.climatology import round_half_up

BUILD_WINDOW_MONTHS = 12
STRETCH_MONTHS = 3
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HAZARD_LABELS = {
    "heavy_rain_days": "heavy rain",
    "heat_days": "extreme heat",
    "wind_days": "high wind",
    "storm_days": "thunderstorms",
}


def fmt_num(x: float) -> str:
    """Numbers in prose, formatted like JavaScript's String(x): 42.4 -> "42.4", 120.0 -> "120"."""
    return f"{x:g}"


def risk_level(share: float) -> str:
    if share < 0.15:
        return "low"
    if share < 0.30:
        return "moderate"
    return "high"


def _label(year: int, month: int) -> str:
    return f"{MONTH_ABBR[month - 1]} {year}"


def build_window(in_service_date: str | None, months: int = BUILD_WINDOW_MONTHS) -> list[tuple[int, int]]:
    """(year, month) pairs for the build window, oldest first. Empty if the date is unknown."""
    dt = _parse(in_service_date)
    if dt is None:
        return []
    out = []
    y, m = dt.year, dt.month
    for _ in range(months):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _best_stretch(rows: list[dict]) -> dict | None:
    """Lowest-risk run of STRETCH_MONTHS consecutive months (earliest wins ties).
    If fewer months are available, the whole run is returned."""
    if not rows:
        return None
    size = min(STRETCH_MONTHS, len(rows))
    best_i, best_sum = 0, None
    for i in range(len(rows) - size + 1):
        s = round_half_up(sum(r["bad_days"] for r in rows[i : i + size]), 1)
        if best_sum is None or s < best_sum:
            best_i, best_sum = i, s
    chunk = rows[best_i : best_i + size]
    return {"start": chunk[0]["label"], "end": chunk[-1]["label"], "bad_days": best_sum}


def window_risk(monthly: list[dict], in_service_date: str | None) -> dict | None:
    """Weather risk across one project's build window, given its location's climatology."""
    window = build_window(in_service_date)
    if not window or not monthly:
        return None
    clim = {r["month"]: r for r in monthly}

    rows = []
    for y, m in window:
        c = clim[m]
        rows.append(
            {
                "ym": f"{y:04d}-{m:02d}",
                "label": _label(y, m),
                "month": m,
                "bad_days": c["bad_days"],
                "bad_share": c["bad_share"],
                "level": risk_level(c["bad_share"]),
            }
        )

    expected = round_half_up(sum(r["bad_days"] for r in rows), 1)
    total_days = sum(clim[m]["days"] for _, m in window)
    share = expected / total_days if total_days else 0.0

    hazard_totals = {
        key: sum(clim[m][key] for _, m in window) for key in HAZARD_LABELS
    }
    dominant_key = max(HAZARD_LABELS, key=lambda k: hazard_totals[k])  # dict order breaks ties

    worst = max(rows, key=lambda r: r["bad_days"])  # first max wins ties
    return {
        "window": f"{rows[0]['label']} – {rows[-1]['label']}",
        "months": rows,
        "expected_bad_days": expected,
        "bad_share": round_half_up(share, 3),
        "level": risk_level(share),
        "high_risk_months": [r["label"] for r in rows if r["level"] == "high"],
        "worst_month": {"label": worst["label"], "bad_days": worst["bad_days"]},
        "best_stretch": _best_stretch(rows),
        "dominant_hazard": HAZARD_LABELS[dominant_key],
    }


def overlap_weather(
    monthly_a: list[dict] | None,
    monthly_b: list[dict] | None,
    project_a: dict,
    project_b: dict,
) -> dict:
    """Weather view of one flagged overlap: each side's build-window risk, plus
    the months where both crews would be in the field at the same time."""
    ra = window_risk(monthly_a or [], project_a.get("in_service_date"))
    rb = window_risk(monthly_b or [], project_b.get("in_service_date"))

    shared_rows: list[dict] = []
    if ra and rb:
        b_by_ym = {r["ym"]: r for r in rb["months"]}
        for r in ra["months"]:
            other = b_by_ym.get(r["ym"])
            if other is None:
                continue
            # Projects are < 25 mi apart, so average the two locations' climatology.
            bad = round_half_up((r["bad_days"] + other["bad_days"]) / 2, 1)
            share = (r["bad_share"] + other["bad_share"]) / 2
            shared_rows.append(
                {
                    "ym": r["ym"],
                    "label": r["label"],
                    "month": r["month"],
                    "bad_days": bad,
                    "bad_share": round_half_up(share, 3),
                    "level": risk_level(share),
                }
            )

    shared_bad = round_half_up(sum(r["bad_days"] for r in shared_rows), 1)
    best_shared = _best_stretch(shared_rows)

    if ra is None or rb is None:
        summary = "Weather risk unavailable — missing climatology or in-service date for one side."
    elif shared_rows:
        high = [r["label"] for r in shared_rows if r["level"] == "high"]
        high_txt = f" {', '.join(high)} {'is' if len(high) == 1 else 'are'} high-risk." if high else ""
        summary = (
            f"Build windows overlap for {len(shared_rows)} month{'s' if len(shared_rows) != 1 else ''} "
            f"({shared_rows[0]['label']} – {shared_rows[-1]['label']}); expect ~{fmt_num(shared_bad)} "
            f"weather-lost days in that shared stretch.{high_txt} Schedule joint field work "
            f"(foundations, stringing) for {best_shared['start']} – {best_shared['end']}."
        )
    else:
        summary = (
            f"Build windows don't overlap in time ({ra['window']} vs {rb['window']}), so weather "
            f"doesn't constrain joint scheduling directly. If crews are shared across both jobs, "
            f"plan field-heavy work for {ra['best_stretch']['start']} – {ra['best_stretch']['end']} "
            f"and {rb['best_stretch']['start']} – {rb['best_stretch']['end']}."
        )

    return {
        "project_a": ra,
        "project_b": rb,
        "shared_months": shared_rows,
        "shared_bad_days": shared_bad,
        "best_shared_stretch": best_shared,
        "summary": summary,
    }
