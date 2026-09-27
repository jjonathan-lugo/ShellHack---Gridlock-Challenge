# Pitch notes — Gridlock

Talking points for judging, pulled from the challenge brief and our own research notes.

## The problem, in one line
Neighboring utilities plan construction years in advance but largely in isolation —
so nearby, same-timeframe projects that could share crews, equipment, or land often
don't get coordinated, wasting money and delaying grid buildout.

## Why this isn't hypothetical
- FERC's Order No. 1920 (2024) exists specifically because utilities have
  historically planned in isolation, causing duplicated, inefficient work — this
  challenge is a hackathon-scale version of that same real coordination problem.
- Our case study utilities aren't arbitrary: Dominion Energy South Carolina and
  Georgia Power share a border (the Savannah River) and both participate in the
  same regional coordination forum (SERTP). DESC also owns an existing hydro plant
  in Martinez, GA, near Augusta — there's already a real cross-utility footprint
  here, not a manufactured example.

## What we built
- Geocoded and cross-referenced both utilities' public construction plans (DESC's
  project descriptions PDF, Georgia Power's 2025 IRP Volume 3) into one dataset.
- Two overlap signals, geography as primary and schedule as secondary, matching the
  brief's own framing: any pair of projects under 25 miles apart (straight-line,
  center-to-center) is flagged, then tiered by how much they could realistically
  share (touching → shared land → shared logistics → shared crew).
- An interactive map (not static) with a ranked list of the top coordination
  opportunities, and a rough, clearly-labeled cost/impact estimate for the
  top-ranked pair.
- 10 real projects in, 6 real flagged overlaps out — most pairs correctly don't
  overlap, which is the point: finding the real matches, not flagging everything.

## Numbers worth saying out loud
- Top-ranked overlap: **Hooks–Thurmond 115kV Tie (DESC)** and **Evans Primary–
  Thurmond Dam 115kV Rebuild (Georgia Power)** — 4.09 mi apart, both near the same
  Savannah River crossing.
- 6 of the pairwise combinations in our dataset overlap under the 25 mi threshold;
  the rest were correctly excluded.

## Add-ons (all built and working)
- **AI coordination agent** (Hugging Face): drafts a plain-English recommendation
  per overlap, with a hallucination guard that checks its distance figure against
  the raw record and falls back to a deterministic template. Recommends; planners decide.
- **Semantic matching** (Hugging Face sentence-transformers): confidence score per
  overlap, plus "near-misses" that read as related but weren't geographically flagged.
- **Weather-risk on build windows**: 10 years of daily history (Open-Meteo / ERA5)
  at every project → expected weather-lost work days per month (heavy rain, extreme
  heat, high wind, thunderstorms), the high-risk months in each build window, and
  the best 3-month stretch for joint field work.
  - Example worth showing: **Jasper–Okatie 230 kV #2 (DESC)** and **McIntosh–Purrysburg
    230 kV reactors (Georgia Power)** have build windows that overlap Jul–Dec 2025,
    so both crews are in the field at once; the panel shows which of those shared
    months carry the most weather risk and suggests the safer stretch.
- **3D "holographic electricity" view** (deck.gl): glowing columns per project
  (taller = more overlaps), energy arcs between overlapping pairs colored by tier,
  animated current pulses, and weather-risk rings.
- **Automatic ingest + autonomous re-computation**: parses both utility PDFs
  (44 DESC projects, 138 Georgia Power projects from the 668-page IRP), geocodes
  every named substation against OpenStreetMap the way Sperry's guide describes,
  flags low-confidence matches, and recomputes overlaps. A watcher rebuilds
  everything when the spreadsheet or PDFs change.
  - **Validation:** handed the spreadsheet's own coordinates, the pipeline
    reproduces all 6 of its overlaps from nothing but the PDFs.
  - **It finds more than the hand-built sheet:** with those same coordinates it
    surfaces 21 overlaps, not 6, because the PDFs contain sibling projects the
    sheet skipped (e.g. Georgia Power's separate Evans Primary – Thurmond Dam **#6**
    rebuild next to the #5 one).
  - **It catches data-entry errors:** the sheet places the McIntosh substation at
    two different points 0.41 mi apart (GPC_2 vs GPC_3); the pipeline reports it.
  - **Live on real OpenStreetMap data:** 172 of 182 projects located, all 6 of the
    sheet's overlaps recovered (median point error 0.0 mi), 74 candidate overlaps.
    Most are low confidence because PDF project names are messy — pitch it as
    "finds candidates for a human to confirm," not "replaces the spreadsheet."

## What's next
- Pull start dates from Georgia Power's per-project detail pages so build windows
  use real construction starts instead of the 12-month planning assumption.
- Line-route geometry (OSM `power=line`) so distance can be closest-point between
  routes, not just center-to-center.
- Swap the illustrative cost assumptions for real utility unit costs.
