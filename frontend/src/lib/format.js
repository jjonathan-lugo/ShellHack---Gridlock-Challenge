// Small display helpers shared across components.

export function fmtDate(value) {
  if (!value) return "date unknown";
  // new Date("2025-06-01") is read as UTC midnight, which is still May 31 in
  // US time zones — build the date from its parts so it stays June.
  const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(String(value));
  const dt = iso ? new Date(+iso[1], +iso[2] - 1, +iso[3]) : new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  return dt.toLocaleDateString("en-US", { year: "numeric", month: "short" });
}

export function daysToReadable(days) {
  if (days == null) return "gap unknown";
  const years = days / 365;
  if (years >= 1) return `${years.toFixed(1)} yr apart`;
  return `${Math.round(days)} days apart`;
}

export function fmtMiles(mi) {
  return `${Number(mi).toFixed(2)} mi`;
}

export function fmtUsdShort(value) {
  return `$${Math.round(value / 1000)}k`;
}

export const UTILITY_COLOR = {
  "Dominion Energy South Carolina": "#1f6feb",
  "Georgia Power": "#e8590c",
};

export function utilityColor(utility) {
  return UTILITY_COLOR[utility] || "#8b949e";
}
