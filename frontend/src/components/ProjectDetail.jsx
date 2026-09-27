// Stub — a project detail card (name, utility, in-service date, tier),
// mirrors the marker popup content in app/app.js.

export default function ProjectDetail({ project }) {
  if (!project) return null;
  return (
    <div className="project-detail">
      <b>{project.project_name}</b>
      <div>{project.utility}</div>
      <div>In-service: {project.in_service_date}</div>
    </div>
  );
}
