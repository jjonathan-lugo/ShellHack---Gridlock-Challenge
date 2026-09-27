"""Weather-risk add-on: flags bad build conditions inside each project's build window.

climatology.py  daily history -> per-calendar-month "lost work day" statistics
risk.py         build window + climatology -> risk summary for a project or an overlap
fetch.py        pulls 10 years of daily history from Open-Meteo (free, no API key)
                and caches the climatology to data/processed/weather_climatology.json

Mirrored in app/weather.js and frontend/src/lib/weather.js so every surface
quotes the same numbers (checked by backend/tests/test_weather.py).
"""
