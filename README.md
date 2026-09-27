# Gridlock Challenge — Utility Coordination Map

A tool that compares Dominion Energy South Carolina (DESC) and Georgia Power (GPC) public
future construction plans and flags where their planned work overlaps geographically
(<25 mi, straight-line between project center points) and by timeline (in-service date gap).

## Run it

No build step or backend required — it's a static page.

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000/app/index.html`.

(Opening `app/index.html` directly via `file://` will not work — the browser blocks
`fetch()` of local JSON files without a server.)

## What's here

```
data/
  Dominion Engery/          # source PDF: DESC public project descriptions
  Georgia Power/            # source PDF: Georgia Power 2025 IRP (public disclosure)
  Projects_Overlaps.xlsx    # geocoded project list + computed overlap table (source of truth)
  processed/
    projects.json           # projects.xlsx sheet, exported for the app
    overlaps.json           # overlaps.xlsx sheet, exported for the app
app/
  index.html                # page shell
  style.css                 # dark theme, map + side panel layout
  app.js                    # Leaflet map, overlap lines, ranked list, cost estimate
guideline/                  # challenge brief + geocoding methodology from Sperry Tech
```

## How overlap is computed

Source data already includes geocoded project centers and a pre-built overlap table
(see `data/Projects_Overlaps.xlsx`, sheets `projects` and `overlaps`). Any pair of
projects under 25 miles apart (straight-line, using each project's center point — the
midpoint of its two named sub-stations/points) is a flagged overlap; the app additionally
buckets each overlap into a coordination tier (touching / <1.6km share land / <8km share
logistics / <40km share crew) and ranks the list by distance, using the in-service date
gap as a secondary signal.

## What the app shows

- Interactive Leaflet map: DESC projects in blue, Georgia Power in orange, flagged
  overlaps drawn as dashed gold lines (thicker = higher-ranked).
- Ranked list of coordination opportunities in the side panel — click a card to zoom
  the map to that pair and see the coordination tier.
- A rough, clearly-labeled cost/impact estimate for the top-ranked overlap (bonus).

## Regenerating the JSON from the spreadsheet

If `Projects_Overlaps.xlsx` changes, re-export the two sheets:

```python
import openpyxl, json, datetime

wb = openpyxl.load_workbook("data/Projects_Overlaps.xlsx", data_only=True)

def cell_str(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    return v

for sheet, out in [("projects", "data/processed/projects.json"), ("overlaps", "data/processed/overlaps.json")]:
    ws = wb[sheet]
    headers = [c.value for c in ws[1]]
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is None:
            continue
        rows.append({k: cell_str(v) for k, v in zip(headers, row)})
    json.dump(rows, open(out, "w"), indent=2)
```

## Next steps / ideas not yet built

- Autonomous re-computation when new project data is added (add-on idea).
- AI agent to draft plain-English coordination recommendations from the ranked list,
  with a self-check step against the raw distance/date data before display.
- Weather-risk overlay on build windows.
- 3D/"electricity" visual treatment (deck.gl) as a stretch visual upgrade.
