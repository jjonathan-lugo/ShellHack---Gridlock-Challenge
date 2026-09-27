// Weather-risk add-on for the React app.
//
// The logic lives in app/weather.js, shared with the static app and checked
// against the Python backend by backend/tests/test_weather.py — importing it
// here (rather than copying it) means there's exactly one JS implementation.

import "../../../app/weather.js";

const W = globalThis.GridlockWeather;
export default W;

const API_BASE = import.meta.env.VITE_API_BASE;

// Cached climatology written by `python3 -m backend.weather.fetch`. The glob
// resolves to {} (not a build error) when the file hasn't been generated yet.
const cached = import.meta.glob("../../../data/processed/weather_climatology.json", {
  eager: true,
  import: "default",
});

const cachedAuto = import.meta.glob("../../../data/processed/auto/weather_climatology_auto.json", {
  eager: true,
  import: "default",
});

/**
 * Per-project monthly climatology that's already available, in order of
 * preference: the backend's /weather (when VITE_API_BASE is set), then the
 * cached JSON in data/processed/. Possibly partial, or {} when there's no
 * cache: the free Open-Meteo tier allows only ~38 ten-year histories a day,
 * so App fetches any pair that's missing live when it's shown.
 * Returns { projects: {id: {lat, lon, monthly}}, origin }.
 */
export async function loadClimatology(dataset = "curated") {
  if (API_BASE && dataset !== "auto") {
    try {
      const res = await fetch(`${API_BASE}/weather`);
      if (res.ok) return { projects: (await res.json()).projects, origin: "api" };
    } catch {
      /* fall through */
    }
  }
  const file = Object.values(dataset === "auto" ? cachedAuto : cached)[0];
  if (file && file.projects) return { projects: file.projects, origin: "cache" };
  return { projects: {}, origin: "live" };
}

/** { project_id: "low" | "moderate" | "high" } for every project with data. */
export function projectRiskLevels(projects, climatology) {
  if (!climatology) return null;
  const out = {};
  for (const p of projects) {
    const c = climatology[p.project_id];
    const r = c && W.windowRisk(c.monthly, p.in_service_date);
    if (r) out[p.project_id] = r;
  }
  return out;
}

export const RISK_HEX = { low: "#3fb950", moderate: "#d29922", high: "#f85149" };
