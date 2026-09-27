// Weather-risk add-on — browser implementation.
//
// One file shared by both UIs: the static app loads it with a <script> tag,
// the React app imports it (frontend/src/lib/weather.js). It mirrors
// backend/weather/climatology.py + risk.py exactly; backend/tests/test_weather.py
// runs both on the same inputs and checks the outputs match.
//
// Exposes window.GridlockWeather (globalThis.GridlockWeather under Node).

(function (root) {
  "use strict";

  const THRESHOLDS = {
    heavy_rain_mm: 25.0,
    heat_c: 35.0,
    wind_gust_kmh: 55.0,
    storm_code_min: 95,
  };
  const DAILY_VARIABLES = ["precipitation_sum", "temperature_2m_max", "wind_gusts_10m_max", "weather_code"];
  const BUILD_WINDOW_MONTHS = 12;
  const STRETCH_MONTHS = 3;
  const MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const HAZARD_LABELS = {
    heavy_rain_days: "heavy rain",
    heat_days: "extreme heat",
    wind_days: "high wind",
    storm_days: "thunderstorms",
  };
  const ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive";
  const PERIOD = { start: "2015-01-01", end: "2024-12-31" };

  function roundHalfUp(x, digits = 1) {
    const f = Math.pow(10, digits);
    return Math.floor(x * f + 0.5) / f;
  }

  const ge = (v, t) => v !== null && v !== undefined && v >= t;

  function classifyDay(precip, tmax, gust, code) {
    const flags = {
      heavy_rain: ge(precip, THRESHOLDS.heavy_rain_mm),
      heat: ge(tmax, THRESHOLDS.heat_c),
      wind: ge(gust, THRESHOLDS.wind_gust_kmh),
      storm: ge(code, THRESHOLDS.storm_code_min),
    };
    flags.bad = flags.heavy_rain || flags.heat || flags.wind || flags.storm;
    return flags;
  }

  function monthlyClimatology(daily) {
    const times = daily.time;
    const col = (k) => daily[k] || new Array(times.length).fill(null);
    const precip = col("precipitation_sum");
    const tmax = col("temperature_2m_max");
    const gust = col("wind_gusts_10m_max");
    const code = col("weather_code");

    const totals = {};
    for (let m = 1; m <= 12; m++) {
      totals[m] = { days: 0, heavy_rain: 0, heat: 0, wind: 0, storm: 0, bad: 0, years: new Set() };
    }
    for (let i = 0; i < times.length; i++) {
      const year = parseInt(times[i].slice(0, 4), 10);
      const month = parseInt(times[i].slice(5, 7), 10);
      const flags = classifyDay(precip[i], tmax[i], gust[i], code[i]);
      const b = totals[month];
      b.days += 1;
      b.years.add(year);
      for (const k of ["heavy_rain", "heat", "wind", "storm", "bad"]) if (flags[k]) b[k] += 1;
    }

    const out = [];
    for (let m = 1; m <= 12; m++) {
      const b = totals[m];
      const n = b.years.size || 1;
      out.push({
        month: m,
        days: roundHalfUp(b.days / n, 1),
        heavy_rain_days: roundHalfUp(b.heavy_rain / n, 1),
        heat_days: roundHalfUp(b.heat / n, 1),
        wind_days: roundHalfUp(b.wind / n, 1),
        storm_days: roundHalfUp(b.storm / n, 1),
        bad_days: roundHalfUp(b.bad / n, 1),
        bad_share: b.days ? roundHalfUp(b.bad / b.days, 3) : 0.0,
      });
    }
    return out;
  }

  function riskLevel(share) {
    if (share < 0.15) return "low";
    if (share < 0.3) return "moderate";
    return "high";
  }

  // Same formats as backend/overlap/timeline_overlap.py: YYYY-MM-DD or M/D/YYYY.
  function parseYearMonth(value) {
    if (!value) return null;
    let y, mo, d;
    let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(value);
    if (m) [y, mo, d] = [+m[1], +m[2], +m[3]];
    else if ((m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(value))) [y, mo, d] = [+m[3], +m[1], +m[2]];
    else return null;
    // Reject impossible dates (13/01, 2/30, 0/1) exactly as Python's strptime does.
    const dt = new Date(Date.UTC(y, mo - 1, d));
    if (mo < 1 || mo > 12 || d < 1 || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null;
    return { year: y, month: mo };
  }

  const label = (y, m) => `${MONTH_ABBR[m - 1]} ${y}`;
  const pad2 = (n) => String(n).padStart(2, "0");
  const sumBad = (rows) => rows.reduce((s, r) => s + r.bad_days, 0);

  function buildWindow(inServiceDate, months = BUILD_WINDOW_MONTHS) {
    const ym = parseYearMonth(inServiceDate);
    if (!ym) return [];
    const out = [];
    let y = ym.year;
    let m = ym.month;
    for (let i = 0; i < months; i++) {
      out.push([y, m]);
      m -= 1;
      if (m === 0) {
        y -= 1;
        m = 12;
      }
    }
    return out.reverse();
  }

  function bestStretch(rows) {
    if (!rows.length) return null;
    const size = Math.min(STRETCH_MONTHS, rows.length);
    let bestI = 0;
    let bestSum = null;
    for (let i = 0; i + size <= rows.length; i++) {
      const s = roundHalfUp(sumBad(rows.slice(i, i + size)), 1);
      if (bestSum === null || s < bestSum) {
        bestI = i;
        bestSum = s;
      }
    }
    const chunk = rows.slice(bestI, bestI + size);
    return { start: chunk[0].label, end: chunk[chunk.length - 1].label, bad_days: bestSum };
  }

  function windowRisk(monthly, inServiceDate) {
    const window = buildWindow(inServiceDate);
    if (!window.length || !monthly || !monthly.length) return null;
    const clim = {};
    monthly.forEach((r) => (clim[r.month] = r));

    const rows = window.map(([y, m]) => ({
      ym: `${y}-${pad2(m)}`,
      label: label(y, m),
      month: m,
      bad_days: clim[m].bad_days,
      bad_share: clim[m].bad_share,
      level: riskLevel(clim[m].bad_share),
    }));

    const expected = roundHalfUp(sumBad(rows), 1);
    const totalDays = window.reduce((s, [, m]) => s + clim[m].days, 0);
    const share = totalDays ? expected / totalDays : 0.0;

    let dominantKey = null;
    let dominantVal = -Infinity;
    for (const key of Object.keys(HAZARD_LABELS)) {
      const v = window.reduce((s, [, m]) => s + clim[m][key], 0);
      if (v > dominantVal) {
        dominantKey = key;
        dominantVal = v;
      }
    }

    let worst = rows[0];
    for (const r of rows) if (r.bad_days > worst.bad_days) worst = r;

    return {
      window: `${rows[0].label} – ${rows[rows.length - 1].label}`,
      months: rows,
      expected_bad_days: expected,
      bad_share: roundHalfUp(share, 3),
      level: riskLevel(share),
      high_risk_months: rows.filter((r) => r.level === "high").map((r) => r.label),
      worst_month: { label: worst.label, bad_days: worst.bad_days },
      best_stretch: bestStretch(rows),
      dominant_hazard: HAZARD_LABELS[dominantKey],
    };
  }

  function overlapWeather(monthlyA, monthlyB, projectA, projectB) {
    const ra = windowRisk(monthlyA || [], projectA && projectA.in_service_date);
    const rb = windowRisk(monthlyB || [], projectB && projectB.in_service_date);

    const shared = [];
    if (ra && rb) {
      const bByYm = {};
      rb.months.forEach((r) => (bByYm[r.ym] = r));
      for (const r of ra.months) {
        const other = bByYm[r.ym];
        if (!other) continue;
        const share = (r.bad_share + other.bad_share) / 2;
        shared.push({
          ym: r.ym,
          label: r.label,
          month: r.month,
          bad_days: roundHalfUp((r.bad_days + other.bad_days) / 2, 1),
          bad_share: roundHalfUp(share, 3),
          level: riskLevel(share),
        });
      }
    }
    const sharedBad = roundHalfUp(sumBad(shared), 1);
    const bestShared = bestStretch(shared);

    let summary;
    if (!ra || !rb) {
      summary = "Weather risk unavailable — missing climatology or in-service date for one side.";
    } else if (shared.length) {
      const high = shared.filter((r) => r.level === "high").map((r) => r.label);
      const highTxt = high.length ? ` ${high.join(", ")} ${high.length === 1 ? "is" : "are"} high-risk.` : "";
      summary =
        `Build windows overlap for ${shared.length} month${shared.length !== 1 ? "s" : ""} ` +
        `(${shared[0].label} – ${shared[shared.length - 1].label}); expect ~${sharedBad} ` +
        `weather-lost days in that shared stretch.${highTxt} Schedule joint field work ` +
        `(foundations, stringing) for ${bestShared.start} – ${bestShared.end}.`;
    } else {
      summary =
        `Build windows don't overlap in time (${ra.window} vs ${rb.window}), so weather ` +
        `doesn't constrain joint scheduling directly. If crews are shared across both jobs, ` +
        `plan field-heavy work for ${ra.best_stretch.start} – ${ra.best_stretch.end} ` +
        `and ${rb.best_stretch.start} – ${rb.best_stretch.end}.`;
    }

    return {
      project_a: ra,
      project_b: rb,
      shared_months: shared,
      shared_bad_days: sharedBad,
      best_shared_stretch: bestShared,
      summary,
    };
  }

  // ---- Data loading: cached file first, then live Open-Meteo from the browser ----

  function archiveUrl(lat, lon) {
    const q = new URLSearchParams({
      latitude: lat.toFixed(4),
      longitude: lon.toFixed(4),
      start_date: PERIOD.start,
      end_date: PERIOD.end,
      daily: DAILY_VARIABLES.join(","),
      timezone: "America/New_York",
    });
    return `${ARCHIVE_URL}?${q}`;
  }

  // Same ~25 km grid as backend/weather/fetch.py (ERA5's resolution): nearby
  // projects share one request, which matters because Open-Meteo's free tier
  // counts a 10-year history as ~260 calls (about two locations a minute).
  const GRID_DEG = 0.25;
  function gridCell(lat, lon) {
    const snap = (x) => Math.round(Math.floor(x / GRID_DEG + 0.5) * GRID_DEG * 10000) / 10000;
    return [snap(lat), snap(lon)];
  }

  // Fetch climatology for `projects` from Open-Meteo, one request per grid
  // cell. On a rate limit, throws an Error with `.rateLimited = true`.
  async function fetchClimatologyLive(projects) {
    const cells = new Map();
    for (const p of projects) {
      if (p.lat_center == null || p.lon_center == null) continue;
      const [lat, lon] = gridCell(p.lat_center, p.lon_center);
      const key = `${lat},${lon}`;
      if (!cells.has(key)) cells.set(key, { lat, lon, members: [] });
      cells.get(key).members.push(p.project_id);
    }
    const out = {};
    // Sequential, to stay polite to the free API.
    for (const { lat, lon, members } of cells.values()) {
      const res = await fetch(archiveUrl(lat, lon));
      if (res.status === 429) {
        const err = new Error("Open-Meteo's free tier allows about two 10-year histories a minute - try again in a minute");
        err.rateLimited = true;
        throw err;
      }
      if (!res.ok) throw new Error(`Open-Meteo returned ${res.status}`);
      const payload = await res.json();
      if (!payload.daily) throw new Error(payload.reason || "Open-Meteo response had no daily block");
      const monthly = monthlyClimatology(payload.daily);
      members.forEach((id) => (out[id] = { lat, lon, monthly }));
    }
    return { source: "Open-Meteo historical archive (live)", period: PERIOD, projects: out };
  }

  // Of `projects`, the located ones with no climatology yet. A project in a
  // grid cell some other project already has is filled in from it for free
  // (mutating `climatology`), so only truly new cells are returned.
  function missingProjects(climatology, projects) {
    const byCell = new Map();
    Object.values(climatology).forEach((c) => byCell.set(`${c.lat},${c.lon}`, c));
    return projects.filter((p) => {
      if (!p || p.lat_center == null || climatology[p.project_id]) return false;
      const [lat, lon] = gridCell(p.lat_center, p.lon_center);
      const hit = byCell.get(`${lat},${lon}`);
      if (hit) {
        climatology[p.project_id] = { lat, lon, monthly: hit.monthly };
        return false;
      }
      return true;
    });
  }

  // The cached file's per-project climatology, or {} if there's no cache yet
  // (the UIs then fetch each clicked pair live via fetchClimatologyLive).
  async function loadCachedClimatology(cacheUrl) {
    try {
      const res = await fetch(cacheUrl);
      if (res.ok) return (await res.json()).projects || {};
    } catch (_) {
      /* no cache */
    }
    return {};
  }

  root.GridlockWeather = {
    THRESHOLDS,
    BUILD_WINDOW_MONTHS,
    MONTH_ABBR,
    roundHalfUp,
    classifyDay,
    monthlyClimatology,
    riskLevel,
    buildWindow,
    windowRisk,
    overlapWeather,
    archiveUrl,
    GRID_DEG,
    gridCell,
    fetchClimatologyLive,
    missingProjects,
    loadCachedClimatology,
  };
})(typeof window !== "undefined" ? window : globalThis);
