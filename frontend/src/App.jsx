import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import MapView from "./components/MapView";
import OverlapPanel from "./components/OverlapPanel";
import ProjectDetail from "./components/ProjectDetail";
import CostEstimate from "./components/CostEstimate";
import WeatherRisk from "./components/WeatherRisk";
import { autoAvailable, indexProjects, loadData } from "./lib/data";
import W, { loadClimatology, projectRiskLevels } from "./lib/weather";

// deck.gl is ~1 MB; only download it when someone switches to 3D.
const HoloView = lazy(() => import("./components/HoloView"));

const INITIAL_DATASET =
  new URLSearchParams(window.location.search).get("dataset") === "auto" ? "auto" : "curated";

export default function App() {
  const [dataset, setDataset] = useState(INITIAL_DATASET);
  const [hasAuto, setHasAuto] = useState(false);
  const [projects, setProjects] = useState([]);
  const [overlaps, setOverlaps] = useState([]);
  const [nearMisses, setNearMisses] = useState([]);
  const [source, setSource] = useState("static");
  const [selectedId, setSelectedId] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState(null);
  const [climatology, setClimatology] = useState(null);
  const [weatherStatus, setWeatherStatus] = useState("loading");
  const [weatherOrigin, setWeatherOrigin] = useState(null);
  const [weatherOverlay, setWeatherOverlay] = useState(false);
  // overlap id -> "pending" | error message, for pairs fetched live on demand
  const [wxFetch, setWxFetch] = useState({});
  const [is3d, setIs3d] = useState(false);

  useEffect(() => {
    autoAvailable().then(setHasAuto);
  }, []);

  function switchDataset(next) {
    const url = new URL(window.location.href);
    if (next === "auto") url.searchParams.set("dataset", "auto");
    else url.searchParams.delete("dataset");
    window.history.replaceState(null, "", url);
    setSelectedId(null);
    setClimatology(null);
    setWxFetch({});
    setWeatherStatus("loading");
    setStatus("loading");
    setDataset(next);
  }

  useEffect(() => {
    let cancelled = false;
    loadData(dataset)
      .then((data) => {
        if (cancelled) return;
        setProjects(data.projects);
        setOverlaps(data.overlaps);
        setNearMisses(data.nearMisses);
        setSource(data.source);
        setStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.message);
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [dataset]);

  // Weather history loads after the projects (it needs their coordinates).
  useEffect(() => {
    if (status !== "ready") return;
    let cancelled = false;
    loadClimatology(dataset).then(({ projects: clim, origin }) => {
      if (cancelled) return;
      setClimatology(clim);
      setWeatherOrigin(origin);
      setWeatherStatus("ready");
    });
    return () => {
      cancelled = true;
    };
  }, [status, dataset]);

  const byId = useMemo(() => indexProjects(projects), [projects]);
  const riskLevels = useMemo(
    () => (weatherOverlay ? projectRiskLevels(projects, climatology) : null),
    [weatherOverlay, projects, climatology]
  );
  const selected = useMemo(
    () => overlaps.find((o) => o.id === selectedId) || null,
    [overlaps, selectedId]
  );
  const topOverlap = overlaps[0] || null;
  const shown = selected || topOverlap;

  // Fetch live the weather for whichever of the shown pair isn't cached yet.
  useEffect(() => {
    if (weatherStatus !== "ready" || !climatology || !shown || wxFetch[shown.id]) return;
    const clim = { ...climatology };
    const need = W.missingProjects(clim, [byId[shown.project_id_a], byId[shown.project_id_b]]);
    if (Object.keys(clim).length !== Object.keys(climatology).length) {
      setClimatology(clim); // filled from a neighbor in the same grid cell
      return;
    }
    if (!need.length) return;
    const id = shown.id;
    setWxFetch((f) => ({ ...f, [id]: "pending" }));
    W.fetchClimatologyLive(need)
      .then((live) => {
        setClimatology((c) => ({ ...c, ...live.projects }));
        setWeatherOrigin("live");
        setWxFetch(({ [id]: _, ...rest }) => rest);
      })
      .catch((err) => {
        console.warn("Weather fetch failed:", err.message);
        setWxFetch((f) => ({ ...f, [id]: err.message }));
      });
  }, [weatherStatus, climatology, shown, byId, wxFetch]);

  function selectOverlap(id) {
    // Clicking a pair whose weather fetch failed retries it.
    setWxFetch((f) => {
      if (!f[id] || f[id] === "pending") return f;
      const { [id]: _failed, ...rest } = f;
      return rest;
    });
    setSelectedId(id);
  }

  return (
    <div className="app-shell">
      <header>
        <h1>Gridlock</h1>
        <div className="subtitle">DESC &amp; Georgia Power planned-construction overlap</div>
        <div className="legend">
          <span className="legend-item">
            <span className="legend-dot" style={{ background: "#1f6feb" }} />
            Dominion Energy South Carolina
          </span>
          <span className="legend-item">
            <span className="legend-dot" style={{ background: "#e8590c" }} />
            Georgia Power
          </span>
          <span className="legend-item">
            <span className="legend-dot" style={{ background: "#f2c744" }} />
            Flagged overlap (&lt;25 mi)
          </span>
          <span className="legend-item source-badge" title={
            source === "api"
              ? "Overlaps recomputed live by the FastAPI backend"
              : "Reading the bundled static export from data/processed/"
          }>
            {source === "api" ? "live API" : "static data"}
          </span>
        </div>
        <div className="view-controls">
          {(hasAuto || dataset === "auto") && (
            <label
              className="toggle"
              title="Hand-geocoded spreadsheet, or the dataset extracted automatically from the utility PDFs"
            >
              Data
              <select value={dataset} onChange={(e) => switchDataset(e.target.value)}>
                <option value="curated">Curated spreadsheet</option>
                <option value="auto">Auto from PDFs</option>
              </select>
            </label>
          )}
          <label
            className="toggle"
            title="Color each project by weather risk across its build window"
          >
            <input
              type="checkbox"
              checked={weatherOverlay}
              onChange={(e) => setWeatherOverlay(e.target.checked)}
            />{" "}
            Weather risk
          </label>
          <button
            type="button"
            className={`toggle-btn${is3d ? " on" : ""}`}
            onClick={() => setIs3d((v) => !v)}
            title="Switch between the 2D map and the 3D holographic view"
          >
            {is3d ? "Back to 2D map" : "3D holographic"}
          </button>
        </div>
      </header>

      {status === "error" && (
        <div className="error-banner">Failed to load data: {error}</div>
      )}

      <div className="map-area">
        {is3d ? (
          <Suspense fallback={<div className="holo-loading">Loading 3D view…</div>}>
            <HoloView
              projects={projects}
              overlaps={overlaps}
              selectedId={selected?.id || null}
              onSelect={setSelectedId}
              riskLevels={riskLevels}
            />
          </Suspense>
        ) : (
          <MapView
            projects={projects}
            overlaps={overlaps}
            selected={selected}
            onSelect={setSelectedId}
            riskLevels={riskLevels}
          />
        )}
        {weatherOverlay && (
          <div className="risk-legend">
            <b>Build-window weather risk</b>
            <span>
              <i className="risk-low" />
              low &lt;15% days lost
            </span>
            <span>
              <i className="risk-moderate" />
              moderate 15–30%
            </span>
            <span>
              <i className="risk-high" />
              high ≥30%
            </span>
          </div>
        )}
      </div>

      <aside className="panel">
        {dataset === "auto" && status === "ready" && (
          <div className="dataset-note">
            Auto-extracted from the utility PDFs ·{" "}
            {projects.filter((p) => p.lat_center != null).length} of {projects.length} projects
            located
          </div>
        )}
        <OverlapPanel
          overlaps={overlaps}
          selectedId={selectedId}
          onSelect={selectOverlap}
          loading={status === "loading"}
        />

        {selected && <ProjectDetail overlap={selected} byId={byId} />}

        <CostEstimate overlap={selected || topOverlap} byId={byId} />

        <WeatherRisk
          overlap={shown}
          byId={byId}
          climatology={climatology}
          status={weatherStatus}
          origin={weatherOrigin}
          fetchState={shown ? wxFetch[shown.id] : undefined}
        />

        {nearMisses.length > 0 && (
          <section className="near-misses">
            <h2>Semantic Near-Misses</h2>
            <p className="near-miss-note">
              High name/description similarity but not geographically flagged —
              worth checking that the geocoded coordinates are right.
            </p>
            <ul>
              {nearMisses.slice(0, 5).map((n) => (
                <li key={`${n.project_id_a}__${n.project_id_b}`}>
                  <span className="sim-score">{n.semantic_similarity.toFixed(2)}</span>
                  {byId[n.project_id_a]?.project_name || n.project_id_a}
                  {" ↔ "}
                  {byId[n.project_id_b]?.project_name || n.project_id_b}
                </li>
              ))}
            </ul>
          </section>
        )}
      </aside>
    </div>
  );
}
