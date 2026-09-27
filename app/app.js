// Gridlock — Utility Coordination Map
// Loads pre-computed project + overlap data (see data/processed/) and renders
// an interactive Leaflet map plus a ranked coordination-opportunity panel.

const DATA_PROJECTS = "../data/processed/projects.json";
const DATA_OVERLAPS = "../data/processed/overlaps.json";

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
  const dt = new Date(d);
  if (isNaN(dt)) return d;
  return dt.toLocaleDateString("en-US", { year: "numeric", month: "short" });
}

function daysToReadable(days) {
  if (days == null) return "unknown gap";
  const years = days / 365;
  if (years >= 1) return `${years.toFixed(1)} yr apart`;
  return `${Math.round(days)} days apart`;
}

async function main() {
  const [projects, overlaps] = await Promise.all([
    fetch(DATA_PROJECTS).then((r) => r.json()),
    fetch(DATA_OVERLAPS).then((r) => r.json()),
  ]);

  const byId = Object.fromEntries(projects.map((p) => [p.project_id, p]));

  // Rank: distance is the primary signal, time gap is a secondary tiebreaker.
  const ranked = [...overlaps].sort((a, b) => {
    if (a.distance_mi !== b.distance_mi) return a.distance_mi - b.distance_mi;
    return (a["time_gap (day)"] ?? Infinity) - (b["time_gap (day)"] ?? Infinity);
  });

  const map = L.map("map", { zoomControl: true }).setView([33.1, -81.6], 8);

  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
    subdomains: "abcd",
    maxZoom: 19,
  }).addTo(map);

  const markerById = {};
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

  const overlapLines = {};
  ranked.forEach((o, idx) => {
    const a = byId[o.project_id_a];
    const b = byId[o.project_id_b];
    if (!a || !b) return;
    const tier = classifyTier(o.distance_mi);
    const weight = Math.max(2, 6 - idx); // closer/higher-ranked overlaps draw thicker
    const line = L.polyline(
      [
        [a.lat_center, a.lon_center],
        [b.lat_center, b.lon_center],
      ],
      {
        color: "#f2c744",
        weight,
        opacity: 0.85,
        className: "overlap-line",
      }
    ).addTo(map);
    line.bindTooltip(
      `${o.distance_mi.toFixed(2)} mi apart · ${tier.label}`,
      { sticky: true }
    );
    overlapLines[o.overlap_id] = line;
  });

  // ---- Ranked list panel ----
  const listEl = document.getElementById("overlap-list");
  const cards = [];

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
      <span class="tier-badge ${tier.cls}">${tier.label}</span>
    `;
    card.addEventListener("click", () => {
      cards.forEach((c) => c.classList.remove("active"));
      card.classList.add("active");
      const grp = L.featureGroup([markerById[o.project_id_a], markerById[o.project_id_b]].filter(Boolean));
      map.fitBounds(grp.getBounds(), { padding: [80, 80], maxZoom: 11 });
      if (markerById[o.project_id_a]) markerById[o.project_id_a].openPopup();
      overlapLines[o.overlap_id]?.setStyle({ weight: 8 });
      setTimeout(() => overlapLines[o.overlap_id]?.setStyle({ weight: Math.max(2, 6 - idx) }), 1200);
    });
    cards.push(card);
    listEl.appendChild(card);
  });

  // ---- Bonus: rough cost/impact estimate for the top-ranked overlap ----
  renderCostEstimate(ranked[0], byId);
}

function renderCostEstimate(top, byId) {
  const box = document.getElementById("cost-estimate");
  if (!top) return;
  const a = byId[top.project_id_a];
  const b = byId[top.project_id_b];
  const tier = classifyTier(top.distance_mi);

  // Rough, illustrative-only heuristic: a shared laydown yard / mobilization
  // setup typically runs ~$120k–$180k per project when built separately.
  // Sharing site logistics (tier: "logistics" or closer) can plausibly avoid
  // 40–60% of one project's setup cost. This is a directional estimate, not
  // a real engineering figure.
  const perYardLow = 120000, perYardHigh = 180000;
  const shareLow = perYardLow * 0.4, shareHigh = perYardHigh * 0.6;

  box.innerHTML = `
    <h2>Bonus: Rough Cost/Impact Estimate</h2>
    <div class="cost-box">
      <div>Top opportunity: <b>${a ? a.project_name : top.project_name_a}</b> &amp;
      <b>${b ? b.project_name : top.project_name_b}</b> — ${top.distance_mi.toFixed(2)} mi apart (${tier.label.toLowerCase()}).</div>
      <div style="margin-top:10px" class="figure">$${Math.round(shareLow / 1000)}k – $${Math.round(shareHigh / 1000)}k</div>
      <div>estimated savings from sharing one laydown yard / site-mobilization setup instead of each utility standing up its own.</div>
      <div class="note">Illustrative only: assumes a typical $${(perYardLow/1000)}k–$${(perYardHigh/1000)}k standalone laydown-yard setup cost per project, with 40–60% of one project's cost avoidable when a nearby project (within site-logistics range) shares the site. Not an engineering estimate — swap in real utility cost data for a production version.</div>
    </div>
  `;
}

main().catch((err) => {
  console.error(err);
  document.getElementById("overlap-list").innerHTML =
    `<div style="color:#ff7b72">Failed to load data: ${err.message}</div>`;
});
