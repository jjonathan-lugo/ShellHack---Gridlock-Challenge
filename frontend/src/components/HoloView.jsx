// 3D "holographic electricity" view. Loaded lazily (React.lazy in App.jsx) so
// deck.gl only downloads when someone actually switches to 3D.

import { useEffect, useMemo, useRef, useState } from "react";
import DeckGL from "@deck.gl/react";
import { BitmapLayer, ColumnLayer, PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import { TileLayer, TripsLayer } from "@deck.gl/geo-layers";
import "../../../app/holo.js"; // shared layer builder (also used by the static app)

const H = globalThis.GridlockHolo;
const NS = { BitmapLayer, ColumnLayer, PathLayer, ScatterplotLayer, TileLayer, TripsLayer };

export default function HoloView({ projects, overlaps, selectedId, onSelect, riskLevels }) {
  const scene = useMemo(() => H.buildScene({ projects, overlaps }), [projects, overlaps]);
  const initialViewState = useMemo(() => H.initialViewState(projects), [projects]);

  // Animation clock for the "current" pulses.
  const [time, setTime] = useState(0);
  const start = useRef(performance.now());
  useEffect(() => {
    let frame;
    const tick = () => {
      setTime(((performance.now() - start.current) / 12) % H.LOOP);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  const weatherLevels = useMemo(() => {
    if (!riskLevels) return null;
    return Object.fromEntries(Object.entries(riskLevels).map(([id, r]) => [id, r.level]));
  }, [riskLevels]);

  const layers = H.buildLayers(NS, scene, { time, selectedId, weatherLevels });

  return (
    <div className="holo-wrap">
      <DeckGL
        initialViewState={initialViewState}
        controller
        layers={layers}
        getTooltip={H.tooltip}
        onClick={(info) => {
          if (info.layer?.id === "holo-arcs" && info.object) onSelect(info.object.id);
        }}
      />
      <div className="holo-hint">Drag to pan · right-drag or ctrl-drag to tilt/rotate · scroll to zoom</div>
    </div>
  );
}
