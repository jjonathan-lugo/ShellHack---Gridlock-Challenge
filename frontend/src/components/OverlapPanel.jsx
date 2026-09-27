import { daysToReadable, fmtMiles } from "../lib/format";

export default function OverlapPanel({ overlaps, selectedId, onSelect, loading }) {
  return (
    <section className="overlap-panel">
      <h2>Top Coordination Opportunities</h2>

      {loading && <div className="empty-state">Loading project data…</div>}

      {!loading && overlaps.length === 0 && (
        <div className="empty-state">
          No overlaps under the 25 mi threshold in this dataset.
        </div>
      )}

      {overlaps.map((o) => (
        <button
          type="button"
          key={o.id}
          className={`overlap-card${selectedId === o.id ? " active" : ""}`}
          onClick={() => onSelect(o.id)}
        >
          <span className="overlap-rank">#{o.rank}</span>
          <span className="overlap-dist">{fmtMiles(o.distance_mi)}</span>

          <div className="overlap-pair">
            <span className="a">● {o.project_name_a}</span>
            <br />
            <span className="b">● {o.project_name_b}</span>
          </div>

          <div className="overlap-meta">
            {daysToReadable(o.time_gap_days)} in-service
            {o.semantic_similarity != null && (
              <> · name similarity {o.semantic_similarity.toFixed(2)}</>
            )}
          </div>

          <span className={`tier-badge ${o.tier_cls}`}>{o.tier_label}</span>
          {o.location_confidence === "low" && (
            <span
              className="conf-badge"
              title="At least one project was located by a weak name match or a town-level fallback — confirm it against the filing (guide Part 2)"
            >
              ⚠ low-confidence location
            </span>
          )}
        </button>
      ))}
    </section>
  );
}
