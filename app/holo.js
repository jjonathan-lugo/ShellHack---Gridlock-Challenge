// 3D "holographic electricity" view — deck.gl layer builder.
//
// Shared by both UIs. It takes the deck.gl namespace as an argument, so the
// static app passes the vendored global `deck` (app/vendor/deckgl) and the
// React app passes the ES-module imports from @deck.gl/*. Same layers either way.
//
//   projects  -> glowing extruded columns (height grows with overlap count),
//                ground rings colored by build-window weather risk when known
//   spans     -> each project's own A-B line, glowing at ground level
//   overlaps  -> 3D energy arcs between the two projects, colored by tier,
//                with animated "current" pulses running along them
//
// Exposes window.GridlockHolo (globalThis.GridlockHolo under Node).

(function (root) {
  "use strict";

  const LOOP = 1000; // animation clock period (arbitrary units)
  const MI_TO_M = 1609.34;

  const UTILITY_RGB = {
    "Dominion Energy South Carolina": [64, 156, 255],
    "Georgia Power": [255, 122, 48],
  };
  const TIER_RGB = {
    coordinate: [255, 123, 114],
    land: [242, 199, 68],
    logistics: [86, 211, 100],
    crew: [121, 192, 255],
    none: [139, 148, 158],
  };
  const RISK_RGB = {
    low: [63, 185, 80],
    moderate: [210, 153, 34],
    high: [248, 81, 73],
  };
  const PULSE_RGB = [255, 244, 170];

  // Additive blending makes overlapping glow layers brighten like light does.
  const GLOW = {
    depthWriteEnabled: false,
    blendColorOperation: "add",
    blendColorSrcFactor: "src-alpha",
    blendColorDstFactor: "one",
    blendAlphaOperation: "add",
    blendAlphaSrcFactor: "one",
    blendAlphaDstFactor: "one-minus-src-alpha",
  };

  function tierKey(distanceMi) {
    const km = distanceMi * 1.60934;
    if (km < 0.1) return "coordinate";
    if (km < 1.6) return "land";
    if (km < 8) return "logistics";
    if (km < 40) return "crew";
    return "none";
  }

  const utilityRgb = (u) => UTILITY_RGB[u] || [139, 148, 158];
  const overlapId = (o) => o.id || o.overlap_id || `${o.project_id_a}__${o.project_id_b}`;
  const located = (p) => p && p.lat_center != null && p.lon_center != null;

  // Points along a raised arc between two centers: [lon, lat, altitude_m].
  function arcPath(a, b, distanceMi, steps = 48) {
    const peak = Math.max(16000, distanceMi * MI_TO_M * 1.3);
    const pts = [];
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      pts.push([
        a.lon_center + (b.lon_center - a.lon_center) * t,
        a.lat_center + (b.lat_center - a.lat_center) * t,
        peak * 4 * t * (1 - t) + 300,
      ]);
    }
    return pts;
  }

  // Timestamps so a pulse travels the path in `duration` clock units, starting at `offset`.
  function timestamps(n, offset, duration) {
    const out = [];
    for (let i = 0; i < n; i++) out.push(offset + (i / (n - 1)) * duration);
    return out;
  }

  function buildScene({ projects, overlaps }) {
    const byId = {};
    projects.forEach((p) => (byId[p.project_id] = p));

    const overlapCount = {};
    overlaps.forEach((o) => {
      overlapCount[o.project_id_a] = (overlapCount[o.project_id_a] || 0) + 1;
      overlapCount[o.project_id_b] = (overlapCount[o.project_id_b] || 0) + 1;
    });

    const nodes = projects.filter(located).map((p) => ({
      id: p.project_id,
      project: p,
      position: [p.lon_center, p.lat_center],
      overlaps: overlapCount[p.project_id] || 0,
      rgb: utilityRgb(p.utility),
    }));

    const spans = projects
      .filter((p) => p.lat_a != null && p.lon_a != null && p.lat_b != null && p.lon_b != null)
      .map((p) => ({
        id: p.project_id,
        project: p,
        path: [
          [p.lon_a, p.lat_a, 150],
          [p.lon_b, p.lat_b, 150],
        ],
        rgb: utilityRgb(p.utility),
      }));

    const arcs = [];
    overlaps.forEach((o, i) => {
      const a = byId[o.project_id_a];
      const b = byId[o.project_id_b];
      if (!located(a) || !located(b)) return;
      const tier = o.tier || tierKey(o.distance_mi);
      arcs.push({
        id: overlapId(o),
        overlap: o,
        a,
        b,
        rank: o.rank || i + 1,
        path: arcPath(a, b, o.distance_mi),
        rgb: TIER_RGB[tier] || TIER_RGB.none,
      });
    });

    // Two staggered pulses per arc, one per span, all looping on the same clock.
    const pulses = [];
    arcs.forEach((arc, i) => {
      const n = arc.path.length;
      const base = (i * 137) % 400;
      pulses.push({ path: arc.path, timestamps: timestamps(n, base, 260) });
      pulses.push({ path: arc.path.slice().reverse(), timestamps: timestamps(n, base + 500, 260) });
    });
    spans.forEach((s, i) => {
      pulses.push({ path: s.path, timestamps: timestamps(2, (i * 211) % 700, 220) });
    });

    // Faint lat/lon grid under everything: the "hologram floor", and a sense of
    // scale even when map tiles can't load (offline demo).
    const grid = [];
    if (nodes.length) {
      const step = 0.25;
      const lons = nodes.map((n) => n.position[0]);
      const lats = nodes.map((n) => n.position[1]);
      const w = Math.floor((Math.min(...lons) - 1.5) / step) * step;
      const e = Math.ceil((Math.max(...lons) + 1.5) / step) * step;
      const s = Math.floor((Math.min(...lats) - 1.5) / step) * step;
      const n = Math.ceil((Math.max(...lats) + 1.5) / step) * step;
      for (let x = w; x <= e + 1e-9; x += step) grid.push({ path: [[x, s], [x, n]], major: Math.abs(x % 1) < 1e-9 });
      for (let y = s; y <= n + 1e-9; y += step) grid.push({ path: [[w, y], [e, y]], major: Math.abs(y % 1) < 1e-9 });
    }

    return { nodes, spans, arcs, pulses, grid };
  }

  // ns: deck.gl namespace (needs ColumnLayer, ScatterplotLayer, PathLayer,
  //     TripsLayer, TileLayer, BitmapLayer).
  // opts.weatherLevels: optional { project_id: "low" | "moderate" | "high" }
  function buildLayers(ns, scene, opts = {}) {
    const time = opts.time || 0;
    const selectedId = opts.selectedId || null;
    const weather = opts.weatherLevels || null;
    const selectedPids = new Set();
    scene.arcs.forEach((a) => {
      if (a.id === selectedId) {
        selectedPids.add(a.a.project_id);
        selectedPids.add(a.b.project_id);
      }
    });

    const layers = [];

    if (opts.basemap !== false) {
      layers.push(
        new ns.TileLayer({
          id: "holo-basemap",
          data: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
          minZoom: 0,
          maxZoom: 19,
          tileSize: 256,
          // Offline: tiles fail quietly and the holographic backdrop shows instead.
          onTileError: () => {},
          renderSubLayers: (props) => {
            const bb = props.tile.boundingBox;
            return new ns.BitmapLayer(props, {
              data: null,
              image: props.data,
              bounds: [bb[0][0], bb[0][1], bb[1][0], bb[1][1]],
              desaturate: 0.85,
              tintColor: [70, 110, 170],
              opacity: 0.55,
            });
          },
        })
      );
    }

    layers.push(
      new ns.PathLayer({
        id: "holo-grid",
        data: scene.grid,
        getPath: (d) => d.path,
        getColor: (d) => (d.major ? [88, 166, 255, 70] : [88, 166, 255, 28]),
        getWidth: (d) => (d.major ? 1.2 : 0.8),
        widthUnits: "pixels",
      }),
      new ns.ScatterplotLayer({
        id: "holo-ground-rings",
        data: scene.nodes,
        getPosition: (d) => d.position,
        getRadius: (d) => (selectedPids.has(d.id) ? 12000 : 8500),
        getFillColor: (d) => {
          const lvl = weather && weather[d.id];
          const rgb = lvl ? RISK_RGB[lvl] : d.rgb;
          return [...rgb, lvl ? 70 : 35];
        },
        getLineColor: (d) => {
          const lvl = weather && weather[d.id];
          return [...(lvl ? RISK_RGB[lvl] : d.rgb), 220];
        },
        stroked: true,
        lineWidthMinPixels: 1.5,
        parameters: GLOW,
        updateTriggers: { getFillColor: [weather], getLineColor: [weather], getRadius: [selectedId] },
      }),
      new ns.PathLayer({
        id: "holo-spans-glow",
        data: scene.spans,
        getPath: (d) => d.path,
        getColor: (d) => [...d.rgb, 60],
        getWidth: 10,
        widthUnits: "pixels",
        capRounded: true,
        parameters: GLOW,
      }),
      new ns.PathLayer({
        id: "holo-spans",
        data: scene.spans,
        getPath: (d) => d.path,
        getColor: (d) => [...d.rgb, 230],
        getWidth: 2,
        widthUnits: "pixels",
      }),
      new ns.ColumnLayer({
        id: "holo-columns",
        data: scene.nodes,
        diskResolution: 24,
        radius: 2600,
        extruded: true,
        pickable: true,
        elevationScale: 1,
        getPosition: (d) => d.position,
        getElevation: (d) => 22000 + 14000 * d.overlaps,
        getFillColor: (d) => [...d.rgb, selectedPids.has(d.id) ? 255 : 190],
        getLineColor: [255, 255, 255, 80],
        material: { ambient: 0.6, diffuse: 0.6, shininess: 48, specularColor: [200, 220, 255] },
        updateTriggers: { getFillColor: [selectedId] },
      }),
      new ns.PathLayer({
        id: "holo-arcs-glow",
        data: scene.arcs,
        getPath: (d) => d.path,
        getColor: (d) => [...d.rgb, d.id === selectedId ? 120 : 55],
        getWidth: (d) => (d.id === selectedId ? 22 : Math.max(8, 18 - d.rank * 2)),
        widthUnits: "pixels",
        capRounded: true,
        jointRounded: true,
        parameters: GLOW,
        updateTriggers: { getColor: [selectedId], getWidth: [selectedId] },
      }),
      new ns.PathLayer({
        id: "holo-arcs",
        data: scene.arcs,
        getPath: (d) => d.path,
        getColor: (d) => [...d.rgb, 235],
        getWidth: (d) => (d.id === selectedId ? 5 : 2.5),
        widthUnits: "pixels",
        jointRounded: true,
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 90],
        updateTriggers: { getWidth: [selectedId] },
      }),
      new ns.TripsLayer({
        id: "holo-pulses",
        data: scene.pulses,
        getPath: (d) => d.path,
        getTimestamps: (d) => d.timestamps,
        getColor: PULSE_RGB,
        widthMinPixels: 5,
        capRounded: true,
        jointRounded: true,
        trailLength: 90,
        currentTime: time % LOOP,
        fadeTrail: true,
        parameters: GLOW,
      })
    );
    return layers;
  }

  function tooltip(info) {
    const o = info && info.object;
    if (!o) return null;
    const style = {
      background: "rgba(13,17,23,0.92)",
      color: "#e6edf3",
      border: "1px solid #30363d",
      borderRadius: "6px",
      fontSize: "12px",
      padding: "8px 10px",
      maxWidth: "320px",
    };
    if (o.overlap) {
      const ov = o.overlap;
      return {
        html: `<b>#${o.rank} · ${Number(ov.distance_mi).toFixed(2)} mi apart</b><br/>${o.a.project_name}<br/>↔ ${o.b.project_name}`,
        style,
      };
    }
    if (o.project) {
      return {
        html: `<b>${o.project.project_name}</b><br/>${o.project.utility}<br/>${o.overlaps} flagged overlap${o.overlaps === 1 ? "" : "s"}`,
        style,
      };
    }
    return null;
  }

  // Camera looking across both utilities' projects at a tilt.
  function initialViewState(projects) {
    const pts = projects.filter(located);
    if (!pts.length) return { longitude: -81.6, latitude: 32.9, zoom: 7, pitch: 55, bearing: -18 };
    const lons = pts.map((p) => p.lon_center);
    const lats = pts.map((p) => p.lat_center);
    const span = Math.max(Math.max(...lons) - Math.min(...lons), Math.max(...lats) - Math.min(...lats));
    return {
      longitude: (Math.max(...lons) + Math.min(...lons)) / 2,
      latitude: (Math.max(...lats) + Math.min(...lats)) / 2 - span * 0.12,
      zoom: Math.max(5, Math.min(10, Math.log2(360 / Math.max(span, 0.01)) + 0.35)),
      pitch: 55,
      bearing: -18,
      maxPitch: 75,
    };
  }

  root.GridlockHolo = { LOOP, TIER_RGB, RISK_RGB, UTILITY_RGB, tierKey, arcPath, buildScene, buildLayers, tooltip, initialViewState };
})(typeof window !== "undefined" ? window : globalThis);
