import { useEffect, useMemo } from "react";
import {
  MapContainer,
  TileLayer,
  Circle,
  CircleMarker,
  Polyline,
  Popup,
  Tooltip,
  useMap,
} from "react-leaflet";
import { fmtDate, fmtMiles, utilityColor } from "../lib/format";
import { RISK_HEX } from "../lib/weather";

const DEFAULT_CENTER = [33.1, -81.6];
const DEFAULT_ZOOM = 8;

/** Fits the map to all plotted projects once they've loaded. */
function FitToProjects({ projects }) {
  const map = useMap();
  useEffect(() => {
    const points = projects
      .filter((p) => p.lat_center != null && p.lon_center != null)
      .map((p) => [p.lat_center, p.lon_center]);
    if (points.length > 0) {
      map.fitBounds(points, { padding: [40, 40] });
    }
  }, [map, projects]);
  return null;
}

/** Zooms to the selected overlap's two projects whenever the selection changes. */
function FlyToSelected({ selected, byId }) {
  const map = useMap();
  useEffect(() => {
    if (!selected) return;
    const a = byId[selected.project_id_a];
    const b = byId[selected.project_id_b];
    const points = [a, b]
      .filter((p) => p && p.lat_center != null)
      .map((p) => [p.lat_center, p.lon_center]);
    if (points.length > 0) {
      map.fitBounds(points, { padding: [80, 80], maxZoom: 11 });
    }
  }, [map, selected, byId]);
  return null;
}

export default function MapView({ projects, overlaps, selected, onSelect, riskLevels }) {
  const byId = useMemo(
    () => Object.fromEntries(projects.map((p) => [p.project_id, p])),
    [projects]
  );

  return (
    <div className="map-wrap">
      <MapContainer
        center={DEFAULT_CENTER}
        zoom={DEFAULT_ZOOM}
        className="map"
        scrollWheelZoom
      >
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />

        <FitToProjects projects={projects} />

        {/* Weather-risk overlay: each project's build-window risk (add-on) */}
        {riskLevels &&
          projects
            .filter((p) => riskLevels[p.project_id] && p.lat_center != null)
            .map((p) => {
              const r = riskLevels[p.project_id];
              return (
                <Circle
                  key={`risk-${p.project_id}`}
                  center={[p.lat_center, p.lon_center]}
                  radius={6000}
                  pathOptions={{
                    color: RISK_HEX[r.level],
                    weight: 2,
                    fillColor: RISK_HEX[r.level],
                    fillOpacity: 0.18,
                  }}
                >
                  <Tooltip sticky>
                    <b>{p.project_name}</b>
                    <br />
                    Build window {r.window}
                    <br />~{r.expected_bad_days} weather-lost days (
                    {Math.round(r.bad_share * 100)}%) · {r.level} risk
                  </Tooltip>
                </Circle>
              );
            })}
        <FlyToSelected selected={selected} byId={byId} />

        {/* Each project's own span, when both sub-points are geocoded */}
        {projects
          .filter(
            (p) =>
              p.lat_a != null && p.lon_a != null && p.lat_b != null && p.lon_b != null
          )
          .map((p) => (
            <Polyline
              key={`span-${p.project_id}`}
              positions={[
                [p.lat_a, p.lon_a],
                [p.lat_b, p.lon_b],
              ]}
              pathOptions={{ color: utilityColor(p.utility), weight: 2, opacity: 0.35 }}
            />
          ))}

        {/* Flagged overlaps — thicker for higher-ranked (closer) pairs */}
        {overlaps.map((o) => {
          const a = byId[o.project_id_a];
          const b = byId[o.project_id_b];
          if (!a || !b || a.lat_center == null || b.lat_center == null) return null;
          const isSelected = selected && selected.id === o.id;
          return (
            <Polyline
              key={`overlap-${o.id}`}
              positions={[
                [a.lat_center, a.lon_center],
                [b.lat_center, b.lon_center],
              ]}
              pathOptions={{
                color: "#f2c744",
                weight: isSelected ? 8 : Math.max(2, 7 - o.rank),
                opacity: isSelected ? 1 : 0.85,
                dashArray: "6 5",
              }}
              eventHandlers={{ click: () => onSelect(o.id) }}
            >
              <Tooltip sticky>
                {fmtMiles(o.distance_mi)} apart · {o.tier_label}
              </Tooltip>
            </Polyline>
          );
        })}

        {/* Project markers */}
        {projects
          .filter((p) => p.lat_center != null && p.lon_center != null)
          .map((p) => {
            const color = utilityColor(p.utility);
            const inSelection =
              selected &&
              (selected.project_id_a === p.project_id ||
                selected.project_id_b === p.project_id);
            return (
              <CircleMarker
                key={`marker-${p.project_id}`}
                center={[p.lat_center, p.lon_center]}
                radius={inSelection ? 11 : 7}
                pathOptions={{
                  color: inSelection ? "#f2c744" : color,
                  weight: inSelection ? 3 : 2,
                  fillColor: color,
                  fillOpacity: 0.55,
                }}
              >
                <Popup>
                  <b>{p.project_name}</b>
                  <br />
                  {p.utility}
                  <br />
                  In-service: {fmtDate(p.in_service_date)}
                </Popup>
              </CircleMarker>
            );
          })}
      </MapContainer>
    </div>
  );
}
