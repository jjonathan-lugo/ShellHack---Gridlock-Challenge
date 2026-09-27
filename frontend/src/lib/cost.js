// Rough, illustrative-only cost/impact estimate for a flagged overlap.
// Mirrors backend/estimate/cost_impact.py so both surfaces quote the same
// figures. These are directional planning assumptions, NOT engineering
// estimates — swap in real utility cost data for anything beyond a demo.

const ASSUMPTIONS = {
  // Standing up a laydown yard / site mobilization for a single project.
  yardSetupLow: 120000,
  yardSetupHigh: 180000,
  // Share of one project's setup avoidable when a nearby project shares it.
  shareFractionLow: 0.4,
  shareFractionHigh: 0.6,
  // Acquiring/clearing right-of-way and access roads, per project.
  rowLow: 260000,
  rowHigh: 420000,
  rowShareFraction: 0.35,
  // Typical laydown yard footprint.
  yardAcres: 5,
  // Mobilizing a line crew to a remote site.
  crewMobLow: 40000,
  crewMobHigh: 75000,
  crewShareFraction: 0.25,
};

export function estimateSavings(overlap) {
  const tierKey = overlap.tier || classifyKeyFromDistance(overlap.distance_mi);

  if (tierKey === "coordinate" || tierKey === "land") {
    const low = ASSUMPTIONS.rowLow * ASSUMPTIONS.rowShareFraction;
    const high = ASSUMPTIONS.rowHigh * ASSUMPTIONS.rowShareFraction;
    return {
      low,
      high,
      basis: "shared right-of-way, access roads, and permitting",
      detail: `At this distance the two projects can plausibly share the access corridor itself rather than each clearing and permitting their own — roughly ${ASSUMPTIONS.yardAcres} acres of duplicated land use avoided.`,
      assumptions: `Assumes $${k(ASSUMPTIONS.rowLow)}–$${k(ASSUMPTIONS.rowHigh)} per project for ROW acquisition/clearing and access roads, with ~${pct(ASSUMPTIONS.rowShareFraction)} avoidable when shared.`,
    };
  }

  if (tierKey === "logistics") {
    const low = ASSUMPTIONS.yardSetupLow * ASSUMPTIONS.shareFractionLow;
    const high = ASSUMPTIONS.yardSetupHigh * ASSUMPTIONS.shareFractionHigh;
    return {
      low,
      high,
      basis: "one shared laydown yard / site mobilization instead of two",
      detail: `Close enough to run deliveries and material staging out of a single ~${ASSUMPTIONS.yardAcres}-acre yard rather than each utility standing up its own.`,
      assumptions: `Assumes a $${k(ASSUMPTIONS.yardSetupLow)}–$${k(ASSUMPTIONS.yardSetupHigh)} standalone laydown-yard setup per project, with ${pct(ASSUMPTIONS.shareFractionLow)}–${pct(ASSUMPTIONS.shareFractionHigh)} of one project's cost avoidable when the site is shared.`,
    };
  }

  if (tierKey === "crew") {
    const low = ASSUMPTIONS.crewMobLow * ASSUMPTIONS.crewShareFraction;
    const high = ASSUMPTIONS.crewMobHigh * ASSUMPTIONS.crewShareFraction;
    return {
      low,
      high,
      basis: "shared crew and specialized equipment mobilization",
      detail:
        "Too far apart to share a site, but within range to sequence the same line crews and specialized equipment across both jobs instead of mobilizing twice.",
      assumptions: `Assumes $${k(ASSUMPTIONS.crewMobLow)}–$${k(ASSUMPTIONS.crewMobHigh)} per crew/equipment mobilization, with ~${pct(ASSUMPTIONS.crewShareFraction)} avoidable through shared scheduling.`,
    };
  }

  return null;
}

function classifyKeyFromDistance(distanceMi) {
  const km = distanceMi * 1.60934;
  if (km < 0.1) return "coordinate";
  if (km < 1.6) return "land";
  if (km < 8) return "logistics";
  if (km < 40) return "crew";
  return "none";
}

const k = (v) => `${Math.round(v / 1000)}k`;
const pct = (v) => `${Math.round(v * 100)}%`;
