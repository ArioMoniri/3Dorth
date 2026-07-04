# GOAL — In-panel imaging viewer, cross-sections, compare, and AR

## One-line goal
Add, in the same panel as the 3D cortical map, a light DICOM/CT **image viewer**
(MPR slices) with a **movable cross-section**, a **side-by-side compare** of two
bones' series and matched cross-sections, and an **AR view** of the 3D bone on a
phone — without exhausting RAM/VRAM and without over-claiming what AR can do.

## Scope & logicality decisions (pre-committed)
- **Not a full OHIF embed.** OHIF needs a DICOMweb backend (Orthanc/dcm4chee) and
  ships a whole app; that is disproportionate for our single-volume, de-identified
  use. We build an **OHIF-*like*** MPR viewer with vtk.js, fed by **slice-on-demand**
  from the API (RAM-friendly — the whole volume never goes to the browser).
- **Compare** reuses the existing Mode-B registration so the *same* anatomical
  cross-section is shown for both sides.
- **AR** ships in two tiers: (1) MVP — export **GLB** and open it in the phone's
  native AR (`<model-viewer>` → iOS Quick Look / Android Scene Viewer), real-world
  via the camera; (2) prototype — **WebXR** in-session with a clipping plane for
  cross-sectioning (Android Chrome; documented device limits). No fabricated AR.

## Phases & gates
| Phase | Deliverable | Gate |
|---|---|---|
| I — Design | Clinical + technical design doc (`docs/IMAGING_DESIGN.md`), API contract, DoD | both personas sign off; contract is coherent + RAM-bounded |
| II — Slice backend | `/api/session/{sid}/slice` (windowed MPR slice PNG) + volume/geometry-for-viewer endpoints; tests | slice endpoint returns correct planes/indices; bounded memory |
| III — MPR viewer (both UIs) | axial/coronal/sagittal + 3D with a movable crosshair; parity | crosshair moves; slices update; parity test green |
| IV — Compare | two linked MPR viewers (registered) side by side | same cross-section shown on both sides |
| V — AR MVP | GLB export + "View in AR" (`<model-viewer>`) button | GLB validates; AR button appears on mobile |
| VI — AR/WebXR prototype | in-AR clipping-plane cross-section (where supported) | works on a WebXR device; degrades gracefully elsewhere |

## Definition of Done (this feature)
- [ ] Image viewer shows the actual CT slices for the loaded scan, correlated with
      the 3D map (click a point → crosshair moves; scrub slices).
- [ ] Movable cross-section plane; compare shows matched cross-sections of two sides.
- [ ] Memory stays bounded (slice-on-demand; no full-volume browser transfer; the
      resource limits in `core/resources.py` still hold).
- [ ] AR MVP: a valid GLB opens in native mobile AR from the UI.
- [ ] Both frontends expose the viewer (parity); every control is real (no placeholders).
- [ ] Tests + watchdog green; honest limitations documented (AR device support,
      de-identified-only, research tool not diagnostic).

## Non-negotiables
- Research tool, not a diagnostic. De-identified data only. Never fabricate a view.
- RAM/VRAM bounded on every deployed device; GPU used for rendering where present.
- Both UIs stay at parity (controls from the registry; viewer feature in both).
