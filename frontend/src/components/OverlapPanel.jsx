// Stub — port the ranked-list rendering + click-to-zoom from app/app.js.

export default function OverlapPanel({ overlaps, onSelect, selected }) {
  return (
    <div id="panel-placeholder">
      <h2>Top Coordination Opportunities</h2>
      <ul>
        {overlaps.map((o, i) => (
          <li key={o.overlap_id || i} onClick={() => onSelect(o)}>
            #{i + 1} — {o.project_name_a} / {o.project_name_b} — {o.distance_mi} mi
          </li>
        ))}
      </ul>
    </div>
  );
}
