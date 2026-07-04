# IMAGING_DESIGN — locked contract (Phase I gate)

Reconciles the clinical review (`IMAGING_DESIGN_clinical.md`, Dr. Kaya) and the
technical design (`IMAGING_DESIGN_technical.md`, M. Vogel). Those two are the
detail; this is the decision record both frontends build against.

## Locked architecture
- **Slice-on-demand, server-side.** The MPR gets windowed 8-bit PNG slices from
  the API (or, in trame, the same core function) — the whole volume never goes to
  the browser. RAM stays bounded (the int16 volume is already resident in
  `SESSIONS`; a slice is a 2D view + one ≤`max_dim` PNG). **Not** a shipped volume,
  **not** cornerstone, **not** a full OHIF/DICOMweb backend.
- **One source of truth: `core/viz/slice.py`** — extract/window/aspect/encode +
  `world↔voxel`. The FastAPI endpoint and trame both import it, so a slice is
  byte-identical across the two UIs (the strongest parity guarantee).
- **Coordinate frame (critical).** The session keeps only `arr[z,y,x]` + `spacing`
  and discarded the DICOM origin/direction. The app world frame is
  `world = idx*spacing + offset_xyz`, identity direction, `(x=col,y=row,z=slice)`.
  Slices, the 3D mesh, and the crosshair all live in this one frame, so the linked
  cursor is exact — but planes are **array-oriented**, labeled
  "axial/coronal/sagittal (array orientation)", and we **never** print anatomical
  A/P/S/I or a laterality we can't derive from the data.

## Clinical honesty rails (gate implementation)
- **Compare is gated on registration quality.** `compare-slice-map` surfaces
  `rms`/`inlier_fraction`; a Poor fit (fitness ≤ 0.3) disables the matched view
  rather than drawing a beautiful lie. The target crosshair is *derived*, never
  independently editable; no automatic side-to-side thickness number is read off
  paired slices (that stays the Mode-B deviation map's job); an uncertainty halo
  ~ RMS marks the matched crosshair.
- **No measurement on slices/reformats** — calipers stay on the source geometry
  (Mode-A/B tools). The slice thickness readout equals the map's vertex value.
- **Orientation/laterality** derived from data or shown "unverified/inferred";
  mirrored panes labeled MIRRORED; anisotropic reformats labeled "interpolated".
- **AR** is for education/consent, never measurement/templating; the GLB bakes in
  a scale reference + laterality + the research/de-identified caveat because it
  leaves the app's guardrails. Persistent footer: de-identified / research only /
  not for diagnosis.

## Locked API contract (all additive, read `SESSIONS`, no second volume copy)
| Endpoint | Purpose |
|---|---|
| `GET /api/session/{sid}/volume-info?side=` | shape, spacing, offset, hu range, bone window preset, plane↔axis map |
| `GET /api/session/{sid}/slice?side=&plane=&index=&window=&level=&max_dim=&overlay=` → PNG | one windowed, aspect-correct slice |
| `POST /api/session/{sid}/pick-to-slices` `{side, world_xyz_mm}` | 3D pick → `{axial,coronal,sagittal}` indices |
| `GET /api/session/{sid}/compare-slice-map` | reference pick → matched target slices via the cached Mode-B transform (409 if not computed; gated on fitness) |
| `GET /api/session/{sid}/model.glb?…` | Draco GLB of the displayed mesh (vertex-colored) for `<model-viewer>` AR |

Plane↔axis: axial=z (x×y), coronal=y (x×z), sagittal=x (y×z). `index` is clamped
into range (scrubbing past the end holds the last slice). Slices run **outside**
`COMPUTE_SEMAPHORE` with a small per-session PNG LRU + client W/L debounce.

## Phase gates (DoD per phase in GOAL_IMAGING.md / WATCHDOG.md)
- **II** `core/viz/slice.py` + `volume-info`/`slice`/`pick-to-slices` + LRU; tests for
  plane/index/window correctness, world↔voxel round-trip, memory-bounded.
- **III** MPR viewer (3 planes + 3D, linked crosshair) in both UIs; parity test.
- **IV** `compare-slice-map` + compare MPR, gated on registration quality.
- **V** GLB export + `model.glb` + `<model-viewer>` AR button (both UIs).
- **VI** React three.js WebXR clip-plane cross-section — Android-Chrome only,
  graceful degradation, never faked (the one honest parity asterisk).
