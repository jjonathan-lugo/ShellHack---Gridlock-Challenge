import { estimateSavings } from "../lib/cost";
import { fmtMiles, fmtUsdShort } from "../lib/format";

export default function CostEstimate({ overlap, byId }) {
  if (!overlap) return null;

  const estimate = estimateSavings(overlap);
  if (!estimate) return null;

  const a = byId[overlap.project_id_a];
  const b = byId[overlap.project_id_b];

  return (
    <section className="cost-estimate">
      <h2>Rough Cost/Impact Estimate</h2>
      <div className="cost-box">
        <div className="cost-pair">
          <b>{a?.project_name || overlap.project_name_a}</b> &amp;{" "}
          <b>{b?.project_name || overlap.project_name_b}</b> —{" "}
          {fmtMiles(overlap.distance_mi)} apart.
        </div>

        <div className="figure">
          {fmtUsdShort(estimate.low)} – {fmtUsdShort(estimate.high)}
        </div>
        <div className="cost-basis">estimated savings from {estimate.basis}.</div>
        <div className="cost-detail">{estimate.detail}</div>

        <div className="note">
          Illustrative only. {estimate.assumptions} Not an engineering estimate —
          swap in real utility cost data for a production version.
        </div>
      </div>
    </section>
  );
}
