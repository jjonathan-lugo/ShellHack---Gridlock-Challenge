# frontend/ (not wired up yet)

This is the React scaffold from the project's planned layout — a future
upgrade path if the team wants component-based state (e.g. live filtering,
the deck.gl 3D add-on, or an agent-recommendation panel that calls the
backend).

**The working demo right now is the static site in `../app/`** (plain
HTML/CSS/JS + Leaflet, reading `../data/processed/*.json` directly — no
build step, no backend required). Start there; only reach for this
scaffold if the app outgrows a single static page.

To stand this up for real:

```bash
npm install
npm run dev
```

`src/App.jsx` and the components below are stubs that port the same logic
already implemented and verified in `app/app.js` (distance tiers, ranking,
click-to-zoom) — see that file as the reference implementation when filling
these in.
