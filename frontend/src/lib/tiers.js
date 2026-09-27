// Coordination tiers, from the challenge notes: closer overlaps are worth more.
// Mirrors backend/overlap/geo_overlap.py::classify_tier so client and server agree.

export const MI_TO_KM = 1.60934;

export const TIERS = {
  coordinate: {
    key: "coordinate",
    label: "Must coordinate (outage timing / crossing structure)",
    short: "Must coordinate",
    cls: "tier-coordinate",
  },
  land: {
    key: "land",
    label: "Can share land itself (ROW, access roads, permits)",
    short: "Share land",
    cls: "tier-land",
  },
  logistics: {
    key: "logistics",
    label: "Can share site logistics (laydown yards, deliveries)",
    short: "Share logistics",
    cls: "tier-logistics",
  },
  crew: {
    key: "crew",
    label: "Can share crew & equipment",
    short: "Share crew",
    cls: "tier-crew",
  },
  none: {
    key: "none",
    label: "Below coordination threshold",
    short: "No overlap",
    cls: "",
  },
};

export function classifyTier(distanceMi) {
  const km = distanceMi * MI_TO_KM;
  if (km < 0.1) return TIERS.coordinate;
  if (km < 1.6) return TIERS.land;
  if (km < 8) return TIERS.logistics;
  if (km < 40) return TIERS.crew;
  return TIERS.none;
}
