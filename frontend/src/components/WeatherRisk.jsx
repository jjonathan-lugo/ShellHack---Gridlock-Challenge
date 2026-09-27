import W from "../lib/weather";
import { utilityColor } from "../lib/format";

function Side({ project, fallbackName, risk }) {
  const color = utilityColor(project?.utility);
  const name = project?.project_name || fallbackName;
  if (!risk) {
    return (
      <div className="wx-side">
        <div className="wx-title">
          <span style={{ color }}>●</span> {name}
        </div>
        <div className="wx-meta">No weather data or in-service date for this project.</div>
      </div>
    );
  }
  const best = risk.best_stretch;
  return (
    <div className="wx-side">
      <div className="wx-title">
        <span style={{ color }}>●</span> {name}
        <span className={`risk-badge risk-${risk.level}`}>{risk.level}</span>
      </div>
      <div className="wx-meta">
        Build window {risk.window} · ~{risk.expected_bad_days} weather-lost days (
        {Math.round(risk.bad_share * 100)}%) · mostly {risk.dominant_hazard}
      </div>
      <div className="wx-strip">
        {risk.months.map((m) => (
          <span
            key={m.ym}
            className={`wx-cell risk-${m.level}`}
            title={`${m.label}: ~${m.bad_days} lost days (${m.level})`}
          >
            {W.MONTH_ABBR[m.month - 1][0]}
          </span>
        ))}
      </div>
      <div className="wx-meta">
        Best 3-month stretch:{" "}
        <b>
          {best.start} – {best.end}
        </b>{" "}
        (~{best.bad_days} lost days)
      </div>
    </div>
  );
}

export default function WeatherRisk({ overlap, byId, climatology, status, origin, fetchState }) {
  if (!overlap) return null;
  const a = byId[overlap.project_id_a];
  const b = byId[overlap.project_id_b];
  const missing = climatology && W.missingProjects({ ...climatology }, [a, b]).length > 0;

  let body;
  if (status === "loading") {
    body = <div className="cost-box wx-status">Loading 10 years of daily weather history…</div>;
  } else if (missing && fetchState && fetchState !== "pending") {
    body = (
      <div className="cost-box wx-status">
        Couldn't load weather history for this pair: {fetchState}. Click the overlap again to
        retry.
      </div>
    );
  } else if (missing) {
    body = (
      <div className="cost-box wx-status">
        Fetching 10 years of daily weather history for this pair from Open-Meteo…
      </div>
    );
  } else {
    const ow = W.overlapWeather(
      climatology[overlap.project_id_a]?.monthly,
      climatology[overlap.project_id_b]?.monthly,
      a,
      b
    );
    body = (
      <div className="cost-box">
        <Side project={a} fallbackName={overlap.project_name_a} risk={ow.project_a} />
        <Side project={b} fallbackName={overlap.project_name_b} risk={ow.project_b} />
        <div className="wx-summary">{ow.summary}</div>
        <div className="note">
          10-year daily history (2015–2024, Open-Meteo / ERA5
          {origin === "live" ? ", fetched live" : origin === "api" ? ", via backend" : ""}) at each
          project. A lost day = ≥25 mm rain, ≥95 °F, gusts ≥34 mph, or thunderstorm. Build window =
          the 12 months up to in-service (planning assumption).
        </div>
      </div>
    );
  }

  return (
    <section className="weather-risk">
      <h2>Build-Window Weather Risk</h2>
      {body}
    </section>
  );
}
