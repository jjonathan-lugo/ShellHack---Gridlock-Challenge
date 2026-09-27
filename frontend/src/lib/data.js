// Data loading + normalization.
//
// Two possible sources, and their field names differ:
//   - bundled static export (data/processed/*.json, straight from the
//     spreadsheet): uses "time_gap (day)", no tier field
//   - the FastAPI backend (/overlaps or /overlaps/semantic): uses
//     "time_gap_days", includes tier/tier_label and optionally
//     semantic_similarity from the Hugging Face model
//
// normalizeOverlap() flattens both into one shape so components don't care
// which one they got.

import projectsStatic from "../../../data/processed/projects.json";
import overlapsStatic from "../../../data/processed/overlaps.json";
import { classifyTier } from "./tiers";

const API_BASE = import.meta.env.VITE_API_BASE;

// Output of the PDF ingest pipeline (python3 -m backend.ingest.pipeline).
// The glob resolves to {} when it hasn't been run, so the build never breaks.
const autoFiles = import.meta.glob("../../../data/processed/auto/*.json", {
  eager: true,
  import: "default",
});
export function autoFile(name) {
  const hit = Object.entries(autoFiles).find(([path]) => path.endsWith(`/${name}`));
  return hit ? hit[1] : null;
}
export const AUTO_BUNDLED = Boolean(autoFile("projects_auto.json"));

/** Is the auto dataset available (bundled, or from the backend)? */
export async function autoAvailable() {
  if (AUTO_BUNDLED) return true;
  if (!API_BASE) return false;
  try {
    return (await fetch(`${API_BASE}/ingest/report`)).ok;
  } catch {
    return false;
  }
}

export function normalizeOverlap(raw) {
  const distance = Number(raw.distance_mi);
  const tier = raw.tier ? { key: raw.tier, label: raw.tier_label } : classifyTier(distance);
  return {
    id: raw.overlap_id || `${raw.project_id_a}__${raw.project_id_b}`,
    project_id_a: raw.project_id_a,
    project_id_b: raw.project_id_b,
    project_name_a: raw.project_name_a,
    project_name_b: raw.project_name_b,
    utility_a: raw.utility_a,
    utility_b: raw.utility_b,
    distance_mi: distance,
    time_gap_days: raw.time_gap_days ?? raw["time_gap (day)"] ?? null,
    tier: tier.key,
    tier_label: tier.label,
    tier_cls: classifyTier(distance).cls,
    semantic_similarity: raw.semantic_similarity ?? null,
    location_confidence: raw.location_confidence ?? null,
  };
}

export function rankOverlaps(overlaps) {
  // Distance is the primary signal; the in-service date gap breaks ties.
  return [...overlaps]
    .sort((a, b) => {
      if (a.distance_mi !== b.distance_mi) return a.distance_mi - b.distance_mi;
      const ga = a.time_gap_days ?? Infinity;
      const gb = b.time_gap_days ?? Infinity;
      return ga - gb;
    })
    .map((o, i) => ({ ...o, rank: i + 1 }));
}

async function loadFromApi() {
  // Prefer the semantic endpoint (adds Hugging Face similarity scores and
  // near-misses); fall back to the plain one if the model isn't available.
  const projects = await fetch(`${API_BASE}/projects`).then((r) => r.json());

  let overlaps = [];
  let nearMisses = [];
  try {
    const res = await fetch(`${API_BASE}/overlaps/semantic`);
    if (!res.ok) throw new Error(`semantic endpoint returned ${res.status}`);
    const payload = await res.json();
    overlaps = payload.overlaps || [];
    nearMisses = payload.near_misses || [];
  } catch {
    overlaps = await fetch(`${API_BASE}/overlaps`).then((r) => r.json());
  }

  return { projects, overlaps, nearMisses };
}

async function loadAuto() {
  if (API_BASE) {
    try {
      const [projects, overlaps] = await Promise.all([
        fetch(`${API_BASE}/projects?dataset=auto`).then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
        fetch(`${API_BASE}/overlaps?dataset=auto`).then((r) => (r.ok ? r.json() : Promise.reject(r.status))),
      ]);
      return { projects, overlaps, source: "api" };
    } catch (err) {
      console.warn("Backend auto dataset unavailable, using bundled files:", err);
    }
  }
  const projects = autoFile("projects_auto.json");
  const overlaps = autoFile("overlaps_auto.json");
  if (!projects || !overlaps) {
    throw new Error("No auto dataset yet — run python3 -m backend.ingest.pipeline");
  }
  return { projects, overlaps, source: "static" };
}

export async function loadData(dataset = "curated") {
  if (dataset === "auto") {
    const auto = await loadAuto();
    return {
      projects: auto.projects,
      overlaps: rankOverlaps(auto.overlaps.map(normalizeOverlap)),
      nearMisses: [],
      source: auto.source,
    };
  }

  let projects = projectsStatic;
  let rawOverlaps = overlapsStatic;
  let nearMisses = [];
  let source = "static";

  if (API_BASE) {
    try {
      const fromApi = await loadFromApi();
      projects = fromApi.projects;
      rawOverlaps = fromApi.overlaps;
      nearMisses = fromApi.nearMisses;
      source = "api";
    } catch (err) {
      // Backend not running is a normal case — fall back silently to the
      // bundled export so the demo never shows an empty screen.
      console.warn("Backend unavailable, using bundled static data:", err.message);
    }
  }

  return {
    projects,
    overlaps: rankOverlaps(rawOverlaps.map(normalizeOverlap)),
    nearMisses,
    source,
  };
}

export function indexProjects(projects) {
  return Object.fromEntries(projects.map((p) => [p.project_id, p]));
}
