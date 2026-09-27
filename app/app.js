// Gridlock — Utility Coordination Map
// Loads pre-computed project + overlap data (see data/processed/) and renders
// an interactive Leaflet map plus a ranked coordination-opportunity panel.

// Two datasets: the hand-geocoded spreadsheet export (default) and, once
// `python3 -m backend.ingest.pipeline` has run, the one extracted
// automatically from the utility PDFs. ?dataset=auto switches.
const DATASETS = {
  curated: {
    projects: "../data/processed/projects.json",
    overlaps: "../data/processed/overlaps.json",
    weather: "../data/processed/weather_climatology.json",
  },
  auto: {
    projects: "../data/processed/auto/projects_auto.json",
    overlaps: "../data/processed/auto/overlaps_auto.json",
    weather: "../data/processed/auto/weather_climatology_auto.json",
  },
};
const DATASET = new URLSearchParams(location.search).get("dataset") === "auto" ? "auto" : "curated";
const DATA_PROJECTS = DATASETS[DATASET].projects;
const DATA_OVERLAPS = DATASETS[DATASET].overlaps;

const UTILITY_COLOR = {
  "Dominion Energy South Carolina": "#1f6feb",
  "Georgia Power": "#e8590c",
};

const MI_TO_KM = 1.60934;

// Distance tiers from the challenge brief: closer overlaps are worth more.
function classifyTier(distanceMi) {
  const km = distanceMi * MI_TO_KM;
  if (km < 0.1) return { key: "coordinate", label: "Must coordinate (outage timing / crossing)", cls: "tier-coordinate" };
  if (km < 1.6) return { key: "land", label: "Can share land itself (ROW, access roads, permits)", cls: "tier-land" };
  if (km < 8) return { key: "logistics", label: "Can share site logistics (laydown, deliveries)", cls: "tier-logistics" };
  if (km < 40) return { key: "crew", label: "Can share crew & equipment", cls: "tier-crew" };
  return { key: "none", label: "Below coordination threshold", cls: "" };
}

function fmtDate(d) {
  if (!d) return "date unknown";
  // new Date("2025-06-01") is read as UTC midnight, which is still May 31 in
  // US time zones — build the date from its parts so it stays June.
  const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(d);
  const dt = iso ? new Date(+iso[1], +iso[2] - 1, +iso[3]) : new Date(d);
  if (isNaN(dt)) return d;
  return dt.toLocaleDateString("en-US", { year: "numeric", month: "short" });
}

function daysToReadable(days) {
  if (days == null) return "unknown gap";
  const years = days / 365;
  if (years >= 1) return `${years.toFixed(1)} yr apart`;
  return `${Math.round(days)} days apart`;
}

const DATA_WEATHER = DATASETS[DATASET].weather;
const W = window.GridlockWeather;
const H = window.GridlockHolo;

const state = {
  projects: [],
  byId: {},
  ranked: [],
  selectedIdx: 0,
  climatology: null, // { project_id: { monthly: [...] } }
  weatherStatus: "loading", // loading | ready
  weatherOrigin: null,
  wxPending: new Set(), // overlap ids whose weather is being fetched live
  wxFailed: new Map(), // overlap id -> error message
  riskLevels: null, // { project_id: level }, computed once per weather load
  weatherOverlay: false,
  is3d: false,
};

let map;
const markerById = {};
const overlapLines = {};
const cards = [];
let riskLayer = null;

async function main() {
  const [projects, overlaps] = await Promise.all([
    fetch(DATA_PROJECTS).then((r) => r.json()),
    fetch(DATA_OVERLAPS).then((r) => r.json()),
  ]);

  state.projects = projects;
  state.byId = Object.fromEntries(projects.map((p) => [p.project_id, p]));
  const byId = state.byId;

  // Rank: distance is the primary signal, time gap is a secondary tiebreaker.
  state.ranked = [...overlaps]
    .sort((a, b) => {
      if (a.distance_mi !== b.distance_mi) return a.distance_mi - b.distance_mi;
      return (a["time_gap (day)"] ?? Infinity) - (b["time_gap (day)"] ?? Infinity);
    })
    .map((o, i) => ({ ...o, rank: i + 1 }));
  const ranked = state.ranked;

  map = L.map("map", { zoomControl: true }).setView([33.1, -81.6], 8);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19,
  }).addTo(map);

  const bounds = [];

  projects.forEach((p) => {
    if (p.lat_center == null || p.lon_center == null) return;
    const color = UTILITY_COLOR[p.utility] || "#999";
    const marker = L.circleMarker([p.lat_center, p.lon_center], {
      radius: 7,
      color,
      weight: 2,
      fillColor: color,
      fillOpacity: 0.55,
    }).addTo(map);

    marker.bindPopup(
      `<b>${p.project_name}</b><br/>${p.utility}<br/>In-service: ${fmtDate(p.in_service_date)}`
    );
    markerById[p.project_id] = marker;
    bounds.push([p.lat_center, p.lon_center]);

    // If both named sub-points are known, draw the project's own span as a thin line.
    if (p.lat_a != null && p.lon_a != null && p.lat_b != null && p.lon_b != null) {
      L.polyline(
        [
          [p.lat_a, p.lon_a],
          [p.lat_b, p.lon_b],
        ],
        { color, weight: 2, opacity: 0.35 }
      ).addTo(map);
    }
  });

  if (bounds.length) map.fitBounds(bounds, { padding: [40, 40] });

  ranked.forEach((o, idx) => {
    const a = byId[o.project_id_a];
    const b = byId[o.project_id_b];
    if (!a || !b) return;
    const tier = classifyTier(o.distance_mi);
    const line = L.polyline(
      [
        [a.lat_center, a.lon_center],
        [b.lat_center, b.lon_center],
      ],
      {
        color: "#f2c744",
        weight: lineWeight(idx),
        opacity: 0.85,
        className: "overlap-line",
      }
    ).addTo(map);
    line.bindTooltip(
      `${o.distance_mi.toFixed(2)} mi apart · ${tier.label}`,
      { sticky: true }
    );
    line.on("click", () => selectOverlap(idx, { zoom: false }));
    overlapLines[o.overlap_id] = line;
  });

  // ---- Ranked list panel ----
  const listEl = document.getElementById("overlap-list");

  ranked.forEach((o, idx) => {
    const a = byId[o.project_id_a];
    const b = byId[o.project_id_b];
    const tier = classifyTier(o.distance_mi);

    const card = document.createElement("div");
    card.className = "overlap-card";
    card.innerHTML = `
      <span class="overlap-rank">#${idx + 1}</span>
      <span class="overlap-dist">${o.distance_mi.toFixed(2)} mi</span>
      <div class="overlap-pair">
        <span class="a">● ${a ? a.project_name : o.project_name_a}</span><br/>
        <span class="b">● ${b ? b.project_name : o.project_name_b}</span>
      </div>
      <div class="overlap-meta">${daysToReadable(o["time_gap (day)"])} in-service &middot; ${o.utility_a.includes("Dominion") ? "SC" : "GA"} / ${o.utility_b.includes("Dominion") ? "SC" : "GA"}</div>
      ${o.location_confidence === "low" ? '<span class="conf-badge" title="At least one project was located by a weak name match or a town-level fallback — confirm it against the filing (guide Part 2)">⚠ low-confidence location</span>' : ""}
      <span class="tier-badge ${tier.cls}">${tier.label}</span>
    `;
    card.addEventListener("click", () => selectOverlap(idx, { zoom: true }));
    cards.push(card);
    listEl.appendChild(card);
  });

  if (!ranked.length) {
    listEl.innerHTML = `<div class="empty-state">No cross-utility overlaps under 25 mi in this dataset.</div>`;
  }

  // Cost + weather panels follow the selection; start on the top-ranked overlap.
  renderPanels();
  setupDatasetSwitch(projects);

  document.getElementById("chk-weather").addEventListener("change", (e) => {
    state.weatherOverlay = e.target.checked;
    renderRiskOverlay();
    if (state.is3d) refreshHolo();
  });
  document.getElementById("btn-3d").addEventListener("click", toggle3d);

  loadWeather();
}

function lineWeight(idx) {
  return Math.max(2, 6 - idx); // closer/higher-ranked overlaps draw thicker
}

function selectOverlap(idx, { zoom }) {
  const o = state.ranked[idx];
  if (!o) return;
  state.selectedIdx = idx;
  state.wxFailed.delete(o.overlap_id); // a click retries a failed weather fetch
  cards.forEach((c, i) => c.classList.toggle("active", i === idx));
  cards[idx]?.scrollIntoView({ block: "nearest", behavior: "smooth" });

  if (zoom && !state.is3d) {
    const grp = L.featureGroup([markerById[o.project_id_a], markerById[o.project_id_b]].filter(Boolean));
    map.fitBounds(grp.getBounds(), { padding: [80, 80], maxZoom: 11 });
    if (markerById[o.project_id_a]) markerById[o.project_id_a].openPopup();
  }
  const line = overlapLines[o.overlap_id];
  line?.setStyle({ weight: 8 });
  setTimeout(() => line?.setStyle({ weight: lineWeight(idx) }), 1200);

  renderPanels();
  if (state.is3d) refreshHolo();
}

function renderPanels() {
  const o = state.ranked[state.selectedIdx];
  renderCostEstimate(o, state.byId, state.selectedIdx === 0);
  renderWeather(o);
}

// ---- Weather risk (add-on) ----

async function setupDatasetSwitch(projects) {
  const note = document.getElementById("dataset-note");
  if (DATASET === "auto") {
    const located = projects.filter((p) => p.lat_center != null).length;
    note.textContent = `Auto-extracted from the utility PDFs · ${located} of ${projects.length} projects located`;
  }
  let autoAvailable = DATASET === "auto";
  if (!autoAvailable) {
    try {
      autoAvailable = (await fetch(DATASETS.auto.projects, { method: "HEAD" })).ok;
    } catch (_) {
      /* no auto dataset */
    }
  }
  if (!autoAvailable) return;
  const wrap = document.getElementById("dataset-switch");
  const sel = wrap.querySelector("select");
  sel.value = DATASET;
  wrap.hidden = false;
  sel.addEventListener("change", () => {
    const url = new URL(location.href);
    if (sel.value === "auto") url.searchParams.set("dataset", "auto");
    else url.searchParams.delete("dataset");
    location.href = url.toString();
  });
}

async function loadWeather() {
  // Whatever's cached (possibly partial: the free Open-Meteo tier only allows
  // ~38 ten-year histories a day). Pairs not in it are fetched live on click.
  state.climatology = await W.loadCachedClimatology(DATA_WEATHER);
  state.weatherOrigin = Object.keys(state.climatology).length ? "cache" : "live";
  state.weatherStatus = "ready";
  finishWeather();
}

// Fetch live whichever of this overlap's two projects has no weather yet.
async function ensureWeather(o) {
  const need = W.missingProjects(state.climatology, [state.byId[o.project_id_a], state.byId[o.project_id_b]]);
  if (!need.length || state.wxPending.has(o.overlap_id) || state.wxFailed.has(o.overlap_id)) return;
  state.wxPending.add(o.overlap_id);
  try {
    const live = await W.fetchClimatologyLive(need);
    Object.assign(state.climatology, live.projects);
    state.weatherOrigin = "live";
  } catch (err) {
    console.warn("Weather fetch failed:", err.message);
    state.wxFailed.set(o.overlap_id, err.message);
  } finally {
    state.wxPending.delete(o.overlap_id);
  }
  finishWeather();
}

function finishWeather() {
  state.riskLevels = projectRiskLevels();
  renderWeather(state.ranked[state.selectedIdx]);
  renderRiskOverlay();
  if (state.is3d) refreshHolo();
}

function projectRiskLevels() {
  if (!state.climatology) return null;
  const levels = {};
  state.projects.forEach((p) => {
    const c = state.climatology[p.project_id];
    const r = c && W.windowRisk(c.monthly, p.in_service_date);
    if (r) levels[p.project_id] = r.level;
  });
  return levels;
}

const RISK_HEX = { low: "#3fb950", moderate: "#d29922", high: "#f85149" };

function renderRiskOverlay() {
  document.getElementById("risk-legend").hidden = !state.weatherOverlay;
  if (riskLayer) {
    riskLayer.remove();
    riskLayer = null;
  }
  if (!state.weatherOverlay || !state.climatology) return;
  const levels = projectRiskLevels();
  riskLayer = L.layerGroup();
  state.projects.forEach((p) => {
    const lvl = levels[p.project_id];
    if (!lvl || p.lat_center == null) return;
    const c = state.climatology[p.project_id];
    const r = W.windowRisk(c.monthly, p.in_service_date);
    L.circle([p.lat_center, p.lon_center], {
      radius: 6000,
      color: RISK_HEX[lvl],
      weight: 2,
      fillColor: RISK_HEX[lvl],
      fillOpacity: 0.18,
      interactive: true,
    })
      .bindTooltip(
        `<b>${p.project_name}</b><br/>Build window ${r.window}<br/>` +
          `~${r.expected_bad_days} weather-lost days (${Math.round(r.bad_share * 100)}%) · ${lvl} risk`,
        { sticky: true }
      )
      .addTo(riskLayer);
  });
  riskLayer.addTo(map);
  riskLayer.eachLayer((l) => l.bringToBack());
}

function riskSideHtml(project, fallbackName, risk) {
  const color = UTILITY_COLOR[project?.utility] || "#999";
  const name = project ? project.project_name : fallbackName;
  if (!risk) {
    return `<div class="wx-side"><div class="wx-title"><span style="color:${color}">●</span> ${name}</div>
      <div class="wx-meta">No weather data or in-service date for this project.</div></div>`;
  }
  const cells = risk.months
    .map(
      (m) =>
        `<span class="wx-cell risk-${m.level}" title="${m.label}: ~${m.bad_days} lost days (${m.level})">${W.MONTH_ABBR[m.month - 1][0]}</span>`
    )
    .join("");
  const best = risk.best_stretch;
  return `
    <div class="wx-side">
      <div class="wx-title"><span style="color:${color}">●</span> ${name}
        <span class="risk-badge risk-${risk.level}">${risk.level}</span></div>
      <div class="wx-meta">Build window ${risk.window} · ~${risk.expected_bad_days} weather-lost days
        (${Math.round(risk.bad_share * 100)}%) · mostly ${risk.dominant_hazard}</div>
      <div class="wx-strip">${cells}</div>
      <div class="wx-meta">Best 3-month stretch: <b>${best.start} – ${best.end}</b> (~${best.bad_days} lost days)</div>
    </div>`;
}

function renderWeather(o) {
  const box = document.getElementById("weather-risk");
  if (!o) return;
  const head = `<h2>Add-on: Build-Window Weather Risk</h2>`;
  if (state.weatherStatus === "loading") {
    box.innerHTML = `${head}<div class="cost-box wx-status">Loading 10 years of daily weather history…</div>`;
    return;
  }
  const a = state.byId[o.project_id_a];
  const b = state.byId[o.project_id_b];
  const clim = state.climatology;
  if (W.missingProjects(clim, [a, b]).length) {
    const failed = state.wxFailed.get(o.overlap_id);
    if (failed) {
      box.innerHTML = `${head}<div class="cost-box wx-status">Couldn't load weather history for this pair: ${failed}.
        Click the overlap again to retry.</div>`;
      return;
    }
    box.innerHTML = `${head}<div class="cost-box wx-status">Fetching 10 years of daily weather history for this pair from Open-Meteo…</div>`;
    ensureWeather(o);
    return;
  }
  const ow = W.overlapWeather(clim[o.project_id_a]?.monthly, clim[o.project_id_b]?.monthly, a, b);

  box.innerHTML = `${head}
    <div class="cost-box">
      ${riskSideHtml(a, o.project_name_a, ow.project_a)}
      ${riskSideHtml(b, o.project_name_b, ow.project_b)}
      <div class="wx-summary">${ow.summary}</div>
      <div class="note">10-year daily history (2015–2024, Open-Meteo / ERA5${state.weatherOrigin === "live" ? ", fetched live" : ""}) at each project.
        A lost day = ≥25 mm rain, ≥95 °F, gusts ≥34 mph, or thunderstorm. Build window = the 12 months up to
        in-service (planning assumption).</div>
    </div>`;
}

// ---- 3D holographic view (add-on) ----

let deckInstance = null;
let holoScene = null;
let holoFrame = null;
let holoStart = 0;

function loadDeckGl() {
  if (window.deck) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "vendor/deckgl/deckgl.min.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("could not load vendor/deckgl/deckgl.min.js"));
    document.head.appendChild(s);
  });
}

function holoLayers(time) {
  const sel = state.ranked[state.selectedIdx];
  return H.buildLayers(window.deck, holoScene, {
    time,
    selectedId: sel ? sel.overlap_id : null,
    weatherLevels: state.weatherOverlay ? state.riskLevels : null,
  });
}

function refreshHolo() {
  if (deckInstance) deckInstance.setProps({ layers: holoLayers(currentHoloTime()) });
}

function currentHoloTime() {
  return ((performance.now() - holoStart) / 12) % H.LOOP;
}

function animateHolo() {
  refreshHolo();
  holoFrame = requestAnimationFrame(animateHolo);
}

async function toggle3d() {
  const btn = document.getElementById("btn-3d");
  const holoEl = document.getElementById("holo");
  const mapEl = document.getElementById("map");

  if (state.is3d) {
    state.is3d = false;
    cancelAnimationFrame(holoFrame);
    holoEl.hidden = true;
    mapEl.style.visibility = "";
    btn.classList.remove("on");
    btn.textContent = "3D holographic";
    map.invalidateSize();
    return;
  }

  btn.disabled = true;
  btn.textContent = "Loading 3D…";
  try {
    await loadDeckGl();
  } catch (err) {
    console.error(err);
    btn.textContent = "3D unavailable";
    return;
  } finally {
    btn.disabled = false;
  }

  state.is3d = true;
  holoEl.hidden = false;
  mapEl.style.visibility = "hidden";
  btn.classList.add("on");
  btn.textContent = "Back to 2D map";

  if (!deckInstance) {
    holoScene = H.buildScene({ projects: state.projects, overlaps: state.ranked });
    holoStart = performance.now();
    deckInstance = new deck.Deck({
      parent: holoEl,
      initialViewState: H.initialViewState(state.projects),
      controller: true,
      layers: holoLayers(0),
      getTooltip: H.tooltip,
      onClick: (info) => {
        if (info.layer && info.layer.id === "holo-arcs" && info.object) {
          const idx = state.ranked.findIndex((o) => o.overlap_id === info.object.id);
          if (idx >= 0) selectOverlap(idx, { zoom: false });
        }
      },
    });
  }
  animateHolo();
}

// Rough, illustrative-only cost/impact assumptions. Mirrors
// backend/estimate/cost_impact.py and frontend/src/lib/cost.js so every
// surface quotes the same figures. Directional planning numbers, NOT
// engineering estimates.
const COST_ASSUMPTIONS = {
  yardSetupLow: 120000,
  yardSetupHigh: 180000,
  shareFractionLow: 0.4,
  shareFractionHigh: 0.6,
  rowLow: 260000,
  rowHigh: 420000,
  rowShareFraction: 0.35,
  yardAcres: 5,
  crewMobLow: 40000,
  crewMobHigh: 75000,
  crewShareFraction: 0.25,
};

function estimateSavings(overlap) {
  const a = COST_ASSUMPTIONS;
  const tier = classifyTier(overlap.distance_mi);
  const k = (v) => `$${Math.round(v / 1000)}k`;
  const pct = (v) => `${Math.round(v * 100)}%`;

  if (tier.key === "coordinate" || tier.key === "land") {
    return {
      low: a.rowLow * a.rowShareFraction,
      high: a.rowHigh * a.rowShareFraction,
      basis: "shared right-of-way, access roads, and permitting",
      detail: `At this distance the two projects can plausibly share the access corridor itself rather than each clearing and permitting their own — roughly ${a.yardAcres} acres of duplicated land use avoided.`,
      assumptions: `Assumes ${k(a.rowLow)}–${k(a.rowHigh)} per project for ROW acquisition/clearing and access roads, with ~${pct(a.rowShareFraction)} avoidable when shared.`,
    };
  }
  if (tier.key === "logistics") {
    return {
      low: a.yardSetupLow * a.shareFractionLow,
      high: a.yardSetupHigh * a.shareFractionHigh,
      basis: "one shared laydown yard / site mobilization instead of two",
      detail: `Close enough to run deliveries and material staging out of a single ~${a.yardAcres}-acre yard rather than each utility standing up its own.`,
      assumptions: `Assumes a ${k(a.yardSetupLow)}–${k(a.yardSetupHigh)} standalone laydown-yard setup per project, with ${pct(a.shareFractionLow)}–${pct(a.shareFractionHigh)} of one project's cost avoidable when the site is shared.`,
    };
  }
  if (tier.key === "crew") {
    return {
      low: a.crewMobLow * a.crewShareFraction,
      high: a.crewMobHigh * a.crewShareFraction,
      basis: "shared crew and specialized equipment mobilization",
      detail:
        "Too far apart to share a site, but within range to sequence the same line crews and specialized equipment across both jobs instead of mobilizing twice.",
      assumptions: `Assumes ${k(a.crewMobLow)}–${k(a.crewMobHigh)} per crew/equipment mobilization, with ~${pct(a.crewShareFraction)} avoidable through shared scheduling.`,
    };
  }
  return null;
}

function renderCostEstimate(top, byId, isTop = true) {
  const box = document.getElementById("cost-estimate");
  if (!top) return;
  const a = byId[top.project_id_a];
  const b = byId[top.project_id_b];
  const tier = classifyTier(top.distance_mi);
  const est = estimateSavings(top);
  if (!est) {
    box.innerHTML = "";
    return;
  }

  box.innerHTML = `
    <h2>Bonus: Rough Cost/Impact Estimate</h2>
    <div class="cost-box">
      <div>${isTop ? "Top opportunity" : `Opportunity #${top.rank}`}: <b>${a ? a.project_name : top.project_name_a}</b> &amp;
      <b>${b ? b.project_name : top.project_name_b}</b> — ${top.distance_mi.toFixed(2)} mi apart (${tier.label.toLowerCase()}).</div>
      <div style="margin-top:10px" class="figure">$${Math.round(est.low / 1000)}k – $${Math.round(est.high / 1000)}k</div>
      <div>estimated savings from ${est.basis}.</div>
      <div style="color:var(--text-dim);font-size:12px;margin-top:6px">${est.detail}</div>
      <div class="note">Illustrative only. ${est.assumptions} Not an engineering estimate — swap in real utility cost data for a production version.</div>
    </div>
  `;
}

main().catch((err) => {
  console.error(err);
  document.getElementById("overlap-list").innerHTML =
    `<div style="color:#ff7b72">Failed to load data: ${err.message}</div>`;
});
