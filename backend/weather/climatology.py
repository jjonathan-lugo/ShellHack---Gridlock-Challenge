"""Turn daily weather history into a per-calendar-month picture of lost work days.

A day counts as a likely lost (or restricted) transmission-construction day if
any of these hit — the usual stop-work triggers for line crews:

  heavy rain      >= 25 mm precipitation   (saturated right-of-way, no heavy equipment access)
  extreme heat    >= 35 C (95 F) max temp  (heat-stress work/rest restrictions)
  high wind       >= 55 km/h (~34 mph) gusts (crane, aerial-lift and conductor-stringing limits)
  thunderstorm    WMO weather code 95-99   (lightning stand-down)

Input is Open-Meteo's `daily` block: parallel arrays keyed by variable name.
Mirrored exactly in app/weather.js and frontend/src/lib/weather.js.
"""

from __future__ import annotations

import math

THRESHOLDS = {
    "heavy_rain_mm": 25.0,
    "heat_c": 35.0,
    "wind_gust_kmh": 55.0,
    "storm_code_min": 95,
}

DAILY_VARIABLES = [
    "precipitation_sum",
    "temperature_2m_max",
    "wind_gusts_10m_max",
    "weather_code",
]


def round_half_up(x: float, digits: int = 1) -> float:
    """Round like JavaScript's Math.round (half away from zero for positives),
    not Python's banker's rounding, so the JS mirrors produce identical output."""
    f = 10 ** digits
    return math.floor(x * f + 0.5) / f


def _ge(value, threshold) -> bool:
    return value is not None and value >= threshold


def classify_day(precip, tmax, gust, code) -> dict:
    t = THRESHOLDS
    flags = {
        "heavy_rain": _ge(precip, t["heavy_rain_mm"]),
        "heat": _ge(tmax, t["heat_c"]),
        "wind": _ge(gust, t["wind_gust_kmh"]),
        "storm": _ge(code, t["storm_code_min"]),
    }
    flags["bad"] = any(flags.values())
    return flags


def monthly_climatology(daily: dict) -> list[dict]:
    """Average hazard days per calendar month across all years in `daily`.

    Returns 12 records (Jan..Dec). Values are averages per occurrence of that
    month, so "bad_days": 6.2 for July means a typical July loses ~6 days.
    """
    times = daily["time"]
    precip = daily.get("precipitation_sum") or [None] * len(times)
    tmax = daily.get("temperature_2m_max") or [None] * len(times)
    gust = daily.get("wind_gusts_10m_max") or [None] * len(times)
    code = daily.get("weather_code") or [None] * len(times)

    totals = {
        m: {"days": 0, "heavy_rain": 0, "heat": 0, "wind": 0, "storm": 0, "bad": 0, "years": set()}
        for m in range(1, 13)
    }
    for i, day in enumerate(times):
        year, month = int(day[0:4]), int(day[5:7])
        flags = classify_day(precip[i], tmax[i], gust[i], code[i])
        bucket = totals[month]
        bucket["days"] += 1
        bucket["years"].add(year)
        for key in ("heavy_rain", "heat", "wind", "storm", "bad"):
            if flags[key]:
                bucket[key] += 1

    out = []
    for m in range(1, 13):
        b = totals[m]
        n = len(b["years"]) or 1
        days = b["days"] / n
        out.append(
            {
                "month": m,
                "days": round_half_up(days, 1),
                "heavy_rain_days": round_half_up(b["heavy_rain"] / n, 1),
                "heat_days": round_half_up(b["heat"] / n, 1),
                "wind_days": round_half_up(b["wind"] / n, 1),
                "storm_days": round_half_up(b["storm"] / n, 1),
                "bad_days": round_half_up(b["bad"] / n, 1),
                "bad_share": round_half_up(b["bad"] / b["days"], 3) if b["days"] else 0.0,
            }
        )
    return out
