import { fmtDate, fmtMiles, daysToReadable, utilityColor } from "../lib/format";

function ProjectCard({ project, fallbackName, fallbackUtility }) {
  const name = project?.project_name || fallbackName;
  const utility = project?.utility || fallbackUtility;
  return (
    <div className="detail-project">
      <div className="detail-name" style={{ color: utilityColor(utility) }}>
        {name}
      </div>
      <div className="detail-sub">{utility}</div>
      <div className="detail-sub">
        In-service: {fmtDate(project?.in_service_date)}
      </div>
      {(project?.name_a || project?.name_b) && (
        <div className="detail-sub">
          Endpoints: {[project.name_a, project.name_b].filter(Boolean).join(" ↔ ")}
        </div>
      )}
    </div>
  );
}

export default function ProjectDetail({ overlap, byId }) {
  if (!overlap) return null;

  const a = byId[overlap.project_id_a];
  const b = byId[overlap.project_id_b];

  return (
    <section className="project-detail">
      <h2>Selected Pair</h2>
      <div className="detail-box">
        <ProjectCard
          project={a}
          fallbackName={overlap.project_name_a}
          fallbackUtility={overlap.utility_a}
        />
        <div className="detail-divider">
          <span>{fmtMiles(overlap.distance_mi)}</span>
          <span className="detail-divider-sub">
            {daysToReadable(overlap.time_gap_days)}
          </span>
        </div>
        <ProjectCard
          project={b}
          fallbackName={overlap.project_name_b}
          fallbackUtility={overlap.utility_b}
        />
        <div className={`tier-badge ${overlap.tier_cls}`}>{overlap.tier_label}</div>
      </div>
    </section>
  );
}
