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

## What's next (roadmap, not yet built)
- Autonomous re-computation when new project data lands (backend already supports
  this — `/overlaps` recomputes live rather than reading a static export).
- An AI agent that drafts the coordination recommendation in plain English, with a
  guard against hallucinated figures, but leaves the final call to human planners.
- Weather-risk overlay on build windows.
- A 3D/"electricity" visual treatment as a stretch upgrade to the current 2D map.
