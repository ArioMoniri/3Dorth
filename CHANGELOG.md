# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- "Surface hole-fill" meshing control (`mesh_close_iters`): morphological closing
  before marching cubes for a smoother, less-lacy surface — display-only; cortical
  thickness is still computed on the raw mask.
- On-image measurement tools (distance / angle) on the 2D reformats, with mm from
  the scan geometry and an "Export with measures" that burns them into the PNG.
- Draggable + resizable overlay panels (colorbar legend, statistics, figures).
- Interactive compute-on-demand backend (`core/pipeline`, `api/routers/session`):
  load a scan, split a bilateral study into sides, and re-run segmentation +
  cortical thickness with the current parameters, so every side-panel control
  affects the result.
- Mode B comparison core: `core/registration` (FPFH+RANSAC → ICP, PCA fallback,
  sagittal mirror), `core/deviation` (signed surface distance with a
  phantom-verified sign convention, cross-check, statistics, diverging figure).
- `core/measurement` (Fig-2 sampling line + height/valid-height bracket) and
  `core/stats` (Table-1 summaries, ANOVA/Tukey/SNK, correlation, regression,
  Fig 3/4/5 plots).
- Both frontends reworked to the compute API: side selector, Apply/Recompute,
  Mode B thickness + deviation, upload.
- Publication-quality figure export (`core/viz.render_thickness_figure`) with a
  crisp discrete colorbar.
- Deployment: Dockerfiles, `docker-compose` profiles, one-line `./deploy.sh`,
  `run.sh`, `Makefile`, pinned `requirements.txt`.
- Real-time UI: every parameter applies automatically — display-only knobs
  re-colour instantly, compute knobs auto-recompute (debounced, superseding), no
  Apply click (`recompute` flag in the registry drives both UIs).
- Region thumbnails: a small render per bone region in the selector
  (click-to-select); region selection now ranks by *boneness* so a table pad is
  never picked over bone.
- Inputs: DICOM `.zip`, NIfTI (`.nii/.nii.gz`), and surface meshes
  (`.stl/.ply/.obj/.vtp`); single-sided/general-bone detection.
- A shipped **de-identified** NIfTI demo (no patient tags) is the default for all
  users, including on the server.
- Multi-format export (PNG/TIFF+DPI, STL/PLY/OBJ/VTP, DICOM) with a camera pose;
  hover tooltip; Mode-B manual anchor + reference/target swap.
- UI switcher + Share panel with a resilient Cloudflare tunnel (`scripts/share.sh`
  survives sleep/wake; the panel polls `/api/config` for the live URL).
- Bounded RAM/compute (`core/resources`): int16 volumes, adaptive resolution,
  serialized computes, LRU session eviction, optional GPU (CuPy) — env-tunable.
- **Imaging viewer + cross-sections + AR** (shipped, both frontends; slice-on-demand
  so the volume never leaves the server — RAM-bounded):
  - MPR viewer (`core/viz/slice`, `/volume-info` · `/slice` · `/pick-to-slices`):
    axial/coronal/sagittal panels with a linked crosshair; 3D pick ↔ slices.
  - Oblique / arbitrary cross-section (`core/viz/slice.oblique_slice`,
    `/oblique-slice`): sample any plane (origin + normal) with an exact
    pixel↔world inverse, so the 3D cut and the 2D reformat match at every point,
    for any tilt — a tiltable cut-plane widget drives a live reformat in both UIs.
  - Compare matched cross-sections (`pipeline.compare_registration`,
    `/compare-slice-map`): registers two sides once, maps a crosshair across
    volumes, **gated on `inlier_fraction ≥ 0.30`** — a low-overlap alignment is
    flagged unreliable, never silently trusted.
  - AR: GLB export (`core/export/mesh` per-vertex colour bake + triangle cap,
    `/model.glb`), `<model-viewer>` (Android Scene Viewer), and a three.js WebXR
    clipping-plane cross-section with a feature-detected graceful fallback.
  - All image panels are array-oriented (never radiological) with the
    research/de-identified/not-for-diagnosis caveat kept visible.

### Changed
- Colormap selection now applies live in the React viewport and legend
  (multi-colormap LUT).
- License changed to Apache 2.0.

### Known limitations
- A bone fused to neighbouring structures in the scan (e.g. an adducted humerus
  against the ribcage) must be isolated with the clip/region tools before Mode B
  is meaningful.
- Single-subject data supports description, not causal inference.

## [0.1.0] — Phase 0–2 foundation
### Added
- Parameter registry (single source of truth), de-identifying DICOM ingest,
  bone segmentation + region labeling + meshing, cortical thickness (local
  thickness with ray-cast validation), Fig-2-faithful rendering.
- FastAPI backend exposing the registry; trame and React frontends; enforced
  feature parity; independent watchdog verifier.
