# frontend/ — React + Vite app

The component-based version of the Gridlock map. Feature-equivalent to the static
`../app/` demo (same data, same tiers, same cost figures), but structured for further
development. Includes the add-ons: build-window weather risk, the 3D "holographic" deck.gl
view (code-split: deck.gl only downloads when you switch to 3D), and the dataset menu for
the auto-extracted PDF dataset.

## Run

```bash
npm install
npm run dev
# then open http://localhost:5173 (keep comments off the npm line in zsh; see the root README)
npm run build    # production bundle into dist/
```

## Data sources

By default it imports the bundled export at `../data/processed/*.json` and works with no
backend at all.

To use the FastAPI backend instead — which recomputes overlaps live and adds the
Hugging Face semantic-similarity scores and near-miss list:

```bash
cp .env.example .env
# set VITE_API_BASE=http://localhost:8000
```

`src/lib/data.js` normalizes both shapes (the static export uses `time_gap (day)`, the API
uses `time_gap_days` and adds tier/similarity fields) into one internal format, and falls
back to the static data if the backend isn't reachable — so a missing backend degrades
instead of showing an empty screen.

Optional generated files are picked up with `import.meta.glob`, so the build works whether
or not they exist yet: `../data/processed/weather_climatology.json` (from `../run-app.sh` or
`python3 -m backend.weather.fetch`) and `../data/processed/auto/*.json` (from
`../run-ingest.sh`). Restart `npm run dev` after generating them. For any overlap whose
projects aren't in the weather cache (or with no cache at all), the app fetches that pair's
history live from Open-Meteo when it's shown — see the root README on free-tier rate limits.

## Structure

```
src/
├── main.jsx                  entry point, imports Leaflet CSS + app styles
├── App.jsx                   data loading, selection state, layout
├── components/
│   ├── MapView.jsx           react-leaflet map: markers, project spans, overlap lines,
│   │                         auto-fit on load, fly-to on selection
│   ├── OverlapPanel.jsx      ranked coordination-opportunity cards
│   ├── ProjectDetail.jsx     selected-pair detail card
│   ├── CostEstimate.jsx      bonus cost/impact estimate
│   ├── WeatherRisk.jsx       build-window weather risk for the selected pair (add-on)
│   └── HoloView.jsx          3D holographic deck.gl view, lazy-loaded (add-on)
├── lib/
│   ├── data.js               loading + normalization + ranking
│   ├── tiers.js              coordination tiers (mirrors backend/overlap/geo_overlap.py)
│   ├── cost.js               cost assumptions (mirrors backend/estimate/cost_impact.py)
│   ├── weather.js            wraps ../app/weather.js + climatology loading
│   └── format.js             date/distance/currency display helpers
└── styles/app.css            dark theme
```

## Note on the mirrored logic

Tier thresholds and cost assumptions exist in three places: here, in `../app/app.js`, and
in `../backend/`. They're kept deliberately identical so all surfaces quote the same
numbers. **If you change one, change all three** — the backend versions are the ones
covered by tests (`python3 -m pytest backend/tests -q`), so start there.

The add-ons avoid that duplication: weather logic and the 3D scene builder live once in
`../app/weather.js` and `../app/holo.js`, imported here, and the weather file is tested for
exact parity with `../backend/weather/`.
