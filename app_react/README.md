# 3Dorth — Frontend 2 (React + vtk.js)

A single-page app at feature parity with the trame frontend. It renders the
demo scan's cortical-thickness map and region geometry client-side with
[vtk.js], and builds its entire control panel by iterating the parameter
registry served from the FastAPI backend — so it can never drift from the
trame UI or the registry.

**All analysis lives in the Python `core/`.** This app contains no analysis
logic; it only fetches from the backend and renders.

## Run

From the repository root, start the API on port 8000:

```bash
.venv/bin/python -m uvicorn api.main:app --port 8000
```

Then, in `app_react/`, start the dev server:

```bash
cd app_react
npm install      # first time only
npm run dev
```

The dev server runs on **http://localhost:5173** and proxies `/api` to
`http://localhost:8000` (see `vite.config.js`), so the SPA can reach
`/api/parameters`, `/api/demo/manifest`, and the static `/api/geometry/*.vtp`
files without any CORS setup.

## Build

```bash
npm run build     # -> dist/  (git-ignored)
npm run preview   # serve the production build locally
```

## What it does

- **Top bar** — app title + Mode A / Mode B toggle.
- **Left panel** — region show/hide checkboxes and a highlight selector (from
  `/api/demo/manifest`), then a registry-driven parameter panel grouped by
  `group` into collapsible sections. Every control from `/api/parameters` is
  rendered (slider for int/float, dropdown for enum, switch for bool) and
  seeded from the API `defaults` (the paper's values). A "Reset to defaults"
  button restores them.
- **Center** — a vtk.js viewport (bone + orientation axes only).
  - *Mode A*: `thickness.vtp` colored by the `thickness_mm` point scalar with a
    discrete green→yellow→red lookup table (`colorbar_steps` bands) over
    `colorbar_range_mm`.
  - *Region view / Mode B toggle off*: one actor per `region_<label>.vtp`;
    checkboxes toggle visibility, the highlighted region is orange, the rest
    neutral.
- **Right overlay** — a crisp HTML/CSS discrete stepped colorbar (not a
  `vtkScalarBarActor`) that live-updates with the coloring controls
  (`mode_a_colormap`, `mode_a_range_min`, `mode_a_range_max`,
  `mode_a_colorbar_steps`, `mode_a_colormap_reverse`).

## Source layout

```
app_react/
  index.html
  vite.config.js          # dev server + /api proxy
  package.json
  src/
    main.jsx              # React entry
    App.jsx               # layout, state, mode toggle, data fetch
    api.js                # fetch helpers (parameters, manifest, geometry)
    colors.js             # discrete GYR LUT + legend band/boundary helpers
    Viewport.jsx          # vtk.js scene (thickness map / region view)
    ControlPanel.jsx      # left panel: regions + registry-driven params
    ParameterControl.jsx  # renders one control by its `control` type
    Legend.jsx            # HTML discrete colorbar
    styles.css
```

[vtk.js]: https://kitware.github.io/vtk-js/
