// Stub — not wired up. See app/app.js for the working reference implementation
// (data loading, ranking, tier classification) this should eventually port.

import { useEffect, useState } from "react";
import MapView from "./components/MapView";
import OverlapPanel from "./components/OverlapPanel";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export default function App() {
  const [projects, setProjects] = useState([]);
  const [overlaps, setOverlaps] = useState([]);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/projects`).then((r) => r.json()).then(setProjects);
    fetch(`${API_BASE}/overlaps`).then((r) => r.json()).then(setOverlaps);
  }, []);

  return (
    <div className="app-shell">
      <MapView projects={projects} overlaps={overlaps} selected={selected} />
      <OverlapPanel overlaps={overlaps} onSelect={setSelected} selected={selected} />
    </div>
  );
}
