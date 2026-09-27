# Gridlock Challenge — Utility Coordination Map

A tool that compares Dominion Energy South Carolina (DESC) and Georgia Power (GPC) public
future construction plans and flags where their planned work overlaps geographically
(<25 mi, straight-line between project center points) and by timeline (in-service date gap).

Built for the Sperry Tech "Gridlock" challenge at ShellHacks 2026.

## Quick start

There are two working UIs. Both show the same data and the same numbers.

**Static app (zero install, works offline) — one command**

```bash
./run-app.sh
```

Starts the local server and opens `http://localhost:8000/app/index.html` in your
browser automatically. Press Ctrl+C to stop. (Equivalent to running
`python3 -m http.server 8000` and opening the URL yourself, if you'd rather do it
manually — set `PORT=xxxx ./run-app.sh` to use a different port.)

It also downloads 10 years of weather history for the weather-risk panel **in the
background** (log: `data/cache/weather_fetch.log`). Open-Meteo's free tier only allows
about two of these downloads a minute, so the first time takes a few minutes; it resumes
where it left off on the next launch and is instant once complete. Until then, the page
fetches the weather for whichever overlap you click, live. Leaflet and deck.gl are
vendored in `app/vendor/`, so once the cache is complete the demo needs no CDN, no npm,
and no network — only the map background tiles require internet (everything else still
renders without them).

It also starts the backend on port 8001 (log: `data/cache/backend.log`) for the **AI
coordination recommendation** panel, if `pip3 install -r backend/requirements.txt` has been
run. For the Hugging Face model, set `HF_TOKEN` first — `export HF_TOKEN=hf_...`, or put
`HF_TOKEN=hf_...` in a `.env` file in the repo root (git-ignored; `run-app.sh` reads it).
Without the backend or a token, the panel shows the same deterministic template computed in
the browser, so it always has an answer.

In the header: **Weather risk** colors each project by build-window weather risk, and
**3D holographic** switches to the deck.gl view. Once you've run the PDF ingest (below),
a **Data** menu appears to switch between the curated spreadsheet and the auto-extracted dataset.

(Opening `app/index.html` via `file://` won't work — browsers block `fetch()` of
local JSON without a server.)

**React app (component-based, for further development)**

```bash
cd frontend
npm install
npm run dev
# then open http://localhost:5173
```

(Type that last line as a separate command, or just open the URL yourself — on
macOS's default zsh, a trailing `# comment` on the same line as `npm run dev` is
NOT treated as a comment like it is in bash, so it gets passed to vite as a real
argument and breaks the dev server. If `npm run dev` ever prints something like
`vite # http://localhost:5173` instead of just `vite`, that's what happened —
rerun the command with nothing after it.)

Runs standalone off the bundled JSON, with the same weather panel, 3D view (deck.gl is
code-split and only downloads when you switch to 3D), and dataset menu. To pull
live-recomputed overlaps plus the Hugging Face semantic scores, copy `.env.example` to
`.env`, set `VITE_API_BASE=http://localhost:8000`, and start the backend below. If the
backend isn't reachable it falls back to the static data automatically.

**Backend API (optional) — one command**

```bash
./run-backend.sh
```

Installs `backend/requirements.txt` if needed, starts the server, and opens
`http://127.0.0.1:8000/docs` once it's ready. Press Ctrl+C to stop. (Equivalent to
`pip install -r backend/requirements.txt` + `uvicorn backend.main:app --reload`,
if you'd rather run it manually — set `PORT=xxxx ./run-backend.sh` for a
different port.)

This installs fast (~10s, no GPU packages) and covers everything except
`/overlaps/semantic`. **Do not add `sentence-transformers` to this file** —
see the warning below.

**Automatic ingest from the utility PDFs (add-on) — one command**

```bash
./run-ingest.sh              # PDFs -> OpenStreetMap coordinates -> overlaps (+ weather)
./run-ingest.sh --watch      # keep running; rebuild whenever the spreadsheet or PDFs change
```

Installs `backend/requirements-ingest.txt` (pdfplumber + pypdf, pure Python) if needed.
Needs internet the first time (OpenStreetMap + Open-Meteo); lookups are cached in
`data/cache/`, so re-runs with `--offline` work without a connection. Takes a few
minutes the first time because Nominatim fallbacks are rate-limited to 1 request/second.

**Tests**

```bash
pip install pytest httpx pdfplumber pypdf
python3 -m pytest backend/tests -q    # 97 passed, 1 skipped (see note below)
```

> **If `pip install` hangs or looks stuck**, it's very likely trying to
> download PyTorch's CUDA/GPU dependencies (several GB — `nvidia-cudnn`,
> `nvidia-cusparselt`, `nvidia-nccl`, etc.), which only happens if something
> in your install requires `sentence-transformers`/`torch` (i.e. you
> installed `backend/requirements-semantic.txt`, not the base
> `requirements.txt`). This is a Linux-only problem — those packages carry a
> `platform_system == Linux` marker and are skipped automatically on macOS —
> but it can still happen if you're running the install *inside a bridged
> environment* (e.g. Cowork's device shell) rather than directly in your own
> Terminal, since that bridge can be a Linux sandbox even when your computer
> is a Mac. Fix: run the install in your own Terminal.app instead of through
> an agent's remote shell, or if you're really on Linux, install the CPU
> build first: `pip install --index-url https://download.pytorch.org/whl/cpu
> torch`, then retry. See `backend/requirements-semantic.txt` for the full
> explanation.

## Layout

```
gridlock-challenge/
├── README.md
├── run-app.sh / run-backend.sh / run-ingest.sh   # one-command launchers
├── data/
│   ├── Dominion Engery/              # source PDF: DESC public project descriptions
│   ├── Georgia Power/                # source PDF: Georgia Power 2025 IRP (public disclosure)
│   ├── Projects_Overlaps.xlsx        # geocoded project list + overlap table (source of truth)
│   ├── raw/
│   │   ├── desc_projects.json        # DESC projects only
│   │   └── gpc_projects.json         # Georgia Power projects only
│   ├── processed/
│   │   ├── projects.json             # exported from the xlsx "projects" sheet
│   │   ├── overlaps.json             # exported from the xlsx "overlaps" sheet
│   │   ├── projects_normalized.geojson
│   │   ├── weather_climatology.json  # created by run-app.sh / backend.weather.fetch
│   │   └── auto/                     # created by run-ingest.sh (PDF-extracted dataset)
│   └── cache/                        # OSM / Nominatim / watcher caches (git-ignored)
│
├── app/                              # static demo — no build step, works offline
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   ├── weather.js                    # weather-risk logic (shared with the React app)
│   ├── agent.js                      # AI recommendation panel client + offline template (shared)
│   ├── holo.js                       # 3D deck.gl scene builder (shared with the React app)
│   └── vendor/                       # Leaflet + deck.gl, vendored so no CDN is needed
│
├── backend/                          # FastAPI service
│   ├── main.py                       # /projects /overlaps /overlaps/semantic /estimate /recommend
│   │                                 # /weather /weather/overlap /ingest/report /health
│   ├── overlap/
│   │   ├── geo_overlap.py            # haversine distance + coordination tiers
│   │   ├── timeline_overlap.py       # in-service date gap
│   │   └── score.py                  # combines both into the ranked list
│   ├── match/
│   │   └── semantic_match.py         # Hugging Face sentence-transformer similarity + near-misses
│   ├── agent/
│   │   ├── recommend.py              # recommendation agent + hallucination guard + offline template
│   │   └── llm_hf.py                 # Hugging Face Inference API binding
│   ├── estimate/
│   │   └── cost_impact.py            # tier-aware cost/impact estimate (bonus item)
│   ├── weather/                      # add-on: build-window weather risk
│   │   ├── climatology.py            # daily history -> lost-work-day stats per month
│   │   ├── risk.py                   # build window + climatology -> risk per project / overlap
│   │   └── fetch.py                  # Open-Meteo history -> weather_climatology.json
│   ├── ingest/                       # add-on: automatic ingest + re-computation
│   │   ├── extract.py                # project tables out of both PDFs
│   │   ├── names.py                  # "A - B 115 kV Rebuild" -> sub-points A, B
│   │   ├── geocode.py                # OSM Overpass + Nominatim matching, with confidence
│   │   ├── pipeline.py               # PDFs -> coordinates -> overlaps + validation report
│   │   ├── xlsx_export.py            # spreadsheet -> JSON, overlaps recomputed
│   │   └── watch.py                  # rebuild automatically when inputs change
│   ├── tests/                        # pytest suite, incl. checks against the spreadsheet
│   ├── requirements.txt
│   ├── requirements-semantic.txt     # optional: sentence-transformers (pulls PyTorch)
│   └── requirements-ingest.txt       # optional: pdfplumber + pypdf
│
├── frontend/                         # React + Vite app
│   ├── index.html
│   ├── vite.config.js
│   ├── .env.example
│   ├── src/
│   │   ├── main.jsx
│   │   ├── App.jsx
│   │   ├── components/               # MapView, OverlapPanel, ProjectDetail, CostEstimate,
│   │   │                             # WeatherRisk, HoloView (lazy-loaded 3D)
│   │   ├── lib/                      # data loading/normalization, tiers, cost, formatting, weather
│   │   └── styles/app.css
│   └── package.json
│
├── notebooks/
│   └── explore_overlap.ipynb         # cross-checks the overlap math against the spreadsheet
│
├── docs/
│   └── pitch_notes.md                # judging talking points
│
└── guideline/                        # challenge brief + geocoding methodology from Sperry Tech
```

## How overlap is computed

Any pair of projects under 25 miles apart is flagged, measured straight-line between
each project's center point (the midpoint of its two named sub-points, or the single
point if only one is geocoded). Each flagged pair is bucketed into a coordination tier
by distance:

| Distance | Tier | What can be shared |
|---|---|---|
| touching / crossing | `coordinate` | outage timing, crossing structures — coordination is mandatory |
| < 1.6 km | `land` | the corridor itself: right-of-way, access roads, permits |
| < 8 km | `logistics` | laydown yards, material deliveries |
| < 40 km | `crew` | crews and specialized equipment |

Ranking is by distance (the primary signal), with the in-service date gap as the
secondary signal and tiebreaker.

**Three independent implementations agree**: `app/app.js`, `frontend/src/lib/`, and
`backend/overlap/`. The backend version is checked against the hand-built spreadsheet
in the test suite — same 6 overlaps out of 25 possible pairs, same distances within
0.1 mi, same time gaps.

## Hugging Face additions

**Semantic project matching** — `backend/match/semantic_match.py`, `GET /overlaps/semantic`
Embeds each project's name + sub-point names with `sentence-transformers/all-MiniLM-L6-v2`
and scores every DESC↔GPC pair by cosine similarity. It enriches each flagged overlap
with a `semantic_similarity` confidence score (close *and* similarly named — e.g. both
mentioning "Thurmond" — beats merely close), and surfaces **near-misses**: pairs that read
as related but weren't geographically flagged, worth checking in case a geocoded point is off.
Needs a separate install — `pip install -r backend/requirements-semantic.txt` — kept out of
the base `requirements.txt` because it pulls PyTorch (see the CUDA-download warning above).

**Coordination-recommendation agent** — `backend/agent/`, `GET /recommend`
Drafts a plain-English suggestion for a flagged overlap. Set `HF_TOKEN` (free at
huggingface.co/settings/tokens) to use a Hugging Face-hosted LLM; without one it returns a
deterministic offline template instead, so it always answers. The response's `source` field
says which path produced it.

The agent is a recommender, not a decision-maker — every output ends by deferring to the
utilities' own planners. A **hallucination guard** verifies that the LLM's stated distance
matches the raw record, retries once if not, and falls back to the template rather than
shipping an unverified number. That behavior is covered by tests.

**Both UIs show it** in an "AI Coordination Recommendation" panel for the selected overlap
(`app/agent.js`, shared by the React app's `AgentRecommendation.jsx`), labeled by what the
guard did: *AI draft · fact-checked*, *AI draft · corrected itself* (its first draft was
rejected and the retry was right), *AI draft rejected · verified template shown* (with the
blocked draft viewable, struck through), or *Template* when no model is available. Answers are
cached per pair on the backend, since the free Hugging Face tier is slow and rate-limited. The
browser's offline template is tested to match the Python one word for word on every overlap.

## Add-ons

### Weather risk on build windows

`backend/weather/`, `app/weather.js`, `GET /weather`, `GET /weather/overlap`

Flags bad build conditions, per the team's add-on list. For every project location it
pulls 10 years (2015–2024) of daily history from Open-Meteo's ERA5 archive (free, no API
key) and counts, per calendar month, the days a line crew would likely lose:

| Hazard | Threshold | Why it stops work |
|---|---|---|
| heavy rain | ≥ 25 mm | saturated right-of-way, no heavy-equipment access |
| extreme heat | ≥ 35 °C / 95 °F | heat-stress work/rest restrictions |
| high wind | gusts ≥ 55 km/h / ~34 mph | crane, aerial-lift and conductor-stringing limits |
| thunderstorm | WMO code 95–99 | lightning stand-down |

**Rate limits.** Open-Meteo's free tier (600 calls/min, 5,000/hour, 10,000/day) counts
every 2 weeks of data at one location as a call, so one 10-year history is ~260 calls —
about two locations a minute and ~38 a day. The fetcher therefore requests one point per
~25 km grid cell (the resolution of the ERA5 reanalysis, so nearby projects share a
request without losing detail), spaces requests 30 s apart, waits out a 429, and saves
after every location so a run cut short by the hourly/daily cap resumes later. For the PDF
dataset it only fetches projects that are in an overlap (22 locations instead of ~100).
Both UIs fetch any pair missing from the cache live when you click it.

Each project's **build window** is the 12 months up to its in-service date (a planning
assumption; the filings give in-service dates, not construction starts). The panel shows
expected weather-lost days across the window, a month-by-month risk strip (low < 15% of
days, moderate 15–30%, high ≥ 30%), the dominant hazard, and the lowest-risk 3-month
stretch. For an overlap it also finds the months **both** crews would be in the field — e.g.
Jasper–Okatie 230 kV #2 (DESC) and McIntosh–Purrysburg (GPC) share Jul–Dec 2025 — and
suggests when to schedule joint field work. The header's **Weather risk** toggle colors every
project on the map (2D and 3D) by its build-window risk.

One JavaScript implementation (`app/weather.js`) serves both UIs; a test runs it and the
Python version on the same inputs for every flagged overlap and requires identical output.

### 3D "holographic electricity" view

`app/holo.js`, `frontend/src/components/HoloView.jsx`

A deck.gl scene behind the header's **3D holographic** button: glowing extruded columns
per project (taller = more flagged overlaps), energy arcs between overlapping pairs colored
by tier, animated current pulses running along arcs and project spans, weather-risk ground
rings, and a lat/lon "hologram floor" grid so it still reads well offline when map tiles
can't load. Hover for details; click an arc to select that overlap in the panel. One scene
builder is shared by both UIs (the static app passes the vendored deck.gl global, React
passes the npm modules).

### Automatic ingest + autonomous re-computation

`backend/ingest/`, `./run-ingest.sh`, `GET /overlaps?dataset=auto`, `GET /ingest/report`

Automates Parts 1–3 of Sperry Tech's `Finding_Real_Locations_Guide`:

1. **Extract** — all 44 DESC projects (one per PDF page: ID, status, in-service date, cost)
   and the 208 rows of Georgia Power's 10-year plan table from the 668-page IRP (138 sponsored
   by Georgia Power itself — `GPC` and its Savannah-area `SAV` rows; `--include-partners`
   adds GTC / MEAG / DU).
2. **Name sub-points** — "EVANS PRIMARY - THURMOND DAM (USA) #5 115KV REBUILD" → Evans Primary,
   Thurmond Dam. Recovers every hand-entered sub-point name in the spreadsheet.
3. **Geocode** — one bulk Overpass query for every named power substation/plant in GA + SC
   (the guide's recommended approach), fuzzy-matched with checks for the right operator and
   the right side of the Savannah River; Nominatim as a fallback. Every match gets a
   **confidence** (high / medium / low); low-confidence overlaps are badged "check location"
   in the UI, per the guide's Part 2.
4. **Recompute** overlaps with the same code as everything else, and write
   `data/processed/auto/` plus `ingest_report.json` comparing against the spreadsheet.

**Validated against the spreadsheet:** given the spreadsheet's own coordinates, the pipeline
starts from nothing but the PDFs and reproduces all 6 of its overlaps (tested). With those
same coordinates it surfaces **21** overlaps rather than 6, because the PDFs include sibling
projects the spreadsheet left out (e.g. Georgia Power's separate Evans Primary – Thurmond
Dam **#6** rebuild). It also caught a data-entry inconsistency: the spreadsheet places the
**McIntosh** substation at two different points 0.41 mi apart (GPC_2 vs GPC_3).

**Live run (real OpenStreetMap + Nominatim):** 172 of 182 projects located, all 6 of the
spreadsheet's overlaps recovered with a median point error of 0.0 mi, and 74 candidate
overlaps in total — most of them low confidence, since the PDF project names are messy.
Matches must fall inside Georgia/South Carolina (the query box also covers FL, AL, TN and
NC, which have their own "Grady", "West End" and "Charleston" substations), except an end
within 30 mi of an in-state partner (e.g. "South Bainbridge – Sinai (FPL)", which really
crosses into Florida). And a project's two ends may not be more than 75 mi apart — if they
are, the weaker match is dropped instead of averaged into a meaningless midpoint.
A test replays the cached live responses (`data/cache/`, git-ignored) whenever they exist.

**Autonomous re-computation** — `./run-ingest.sh --watch` (or `python3 -m backend.ingest.watch`)
watches `Projects_Overlaps.xlsx` and the PDFs. Edit the spreadsheet and it re-exports
`projects.json`, recomputes `overlaps.json`, reports any disagreement with the sheet's own
overlaps tab, and fetches weather for any new project; change a PDF and it re-runs the
ingest pipeline. Refresh the browser to see the result. Re-exporting the current workbook
reproduces the committed JSON byte for byte (tested), so the watcher never churns the data.

## Status

Everything in the tree is implemented — no stubs or placeholder files.

| Piece | Status |
|---|---|
| `app/` static map, ranked list, cost estimate | Working — verified rendering headlessly (6 cards, click-to-zoom, correct figures) |
| `frontend/` React app | Working — `npm run build` clean, verified rendering headlessly |
| `backend/overlap/` | Working — matches the spreadsheet exactly, covered by tests |
| `backend/estimate/` | Working — tier-aware, covered by tests |
| `backend/agent/` | Working — template path and hallucination guard covered by tests; **live HF model call verified against the real Inference API**; shown in both UIs (headless-browser checked with a scripted model: pass, self-correction, and blocked draft) |
| `backend/match/` | Working — **verified against the live Hub** (`/overlaps/semantic` downloads and runs `all-MiniLM-L6-v2` for real) |
| Weather risk (`backend/weather/`, `app/weather.js`) | Working — logic, Python↔JS parity, API, rate-limit pacing/resume, and both UIs' on-click fetch covered by tests / headless renders; **a complete live Open-Meteo download not yet finished** (the first attempt hit the free-tier limit, which is what the pacing now handles) |
| 3D view (`app/holo.js`, `HoloView.jsx`) | Working — renders and animates in both UIs (headless WebGL), scene builder covered by tests |
| PDF ingest (`backend/ingest/`) | Working — **run live against OpenStreetMap**: 172 of 182 projects located, all 6 of the spreadsheet's overlaps recovered, median point error 0.0 mi. Covered by tests, including a replay of the cached live data |
| Test suite | 132 passed, 1 skipped |

Everything has been run end to end, including the Hugging Face pieces, with a real
`HF_TOKEN` on an unrestricted network. (They were originally built and unit-tested in a
sandbox that blocks outbound access to `huggingface.co`, using a mocked embedder and a
faked LLM — that's why the test suite still has one self-skipping test for
`/overlaps/semantic`, which skips only when the model genuinely can't be reached rather
than falsely passing.)

**Honest gaps, for the add-ons**:

- The PDF geocoding has now run live. Most automatic matches are low confidence (the PDF
  project names are messy), so present the auto dataset as *candidates for a human to
  confirm*, with the spreadsheet as the primary demo. Two real-data problems were found
  and fixed: OSM has two "Goshen Substation"s 87 mi apart (each project's two endpoints
  now disambiguate each other), and "Hooks" isn't in OSM at all, so the fallback found
  "Hooks Pond" 165 mi away (now rejected; the project centers on its other endpoint, as
  the spreadsheet does). Out-of-state namesakes were also producing false overlaps (an SC
  and a GA project both matched to towns in North Carolina); matches are now limited to
  GA/SC.
- The weather numbers have so far only been exercised with synthetic history in tests;
  **let `./run-app.sh` finish its background download before demoing** and read the risk
  levels it produces.

## Regenerating the processed JSON from the spreadsheet

If `Projects_Overlaps.xlsx` changes:

```bash
python3 -m backend.ingest.xlsx_export
```

That writes `data/processed/projects.json`, recomputes `overlaps.json` from the project
coordinates, and prints any disagreement with the sheet's own "overlaps" tab. Or let
`./run-ingest.sh --watch` do it automatically on every save. Then re-run
`python3 -m pytest backend/tests -q` to confirm everything still matches.
