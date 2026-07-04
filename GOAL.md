# GOAL

## One-line goal
Build a general-purpose, reproducible web application for quantitative 3D bone
analysis from CT, with **one shared Python analysis core** and **two
interchangeable frontends** (trame + React/vtk.js), supporting two modes:

- **Mode A — cortical thickness mapping** (single scan), faithfully reproducing
  Guo et al. 2022 (Eur J Med Res 27:102): per-surface cortical thickness in mm,
  a Fig-2-style discrete mm colorbar, and the paper's point/line/height tools.
- **Mode B — two-scan comparison** (e.g. operated vs contralateral shoulder):
  reconstruct both bones, auto-register, compute a signed millimetric
  surface-deviation map (bone gain vs loss), quantify it.

The tool is **general** — not hardcoded to the proximal humerus. It loads
whatever bone(s) are present, lets the user filter/segment regions after
loading, and exposes anatomy-specific choices as interactive controls.

## Research question (first user)
Does anchor/tendon-repair surgery cause long-term bony remodeling in the
proximal humerus? The bilateral shoulder CT (operated vs contralateral) is the
first test case for Mode B. **One subject supports description, not causal
inference** — bilateral asymmetry (dominant-arm size) is a confounder.

## Success criteria (definition of "done for the whole project")
See `docs/DEFINITION_OF_DONE.md` for the full checklist. Headline gates:
1. Ingest recurses past the Weasis wrapper to `dicom/`; reports geometry,
   laterality, hardware, and confirms the two scans are distinct.
2. Clean segmentation; region toggles + highlight work; analysis respects the
   current selection.
3. Mode A: local-thickness ≈ ray-cast within tolerance; Fig-2 discrete mm
   colorbar; line (N points) + height bracket overlays match the figure.
4. Mode B: anchor-region ICP RMS below the stated threshold; overlay aligned;
   signed-distance **sign verified on a test point**; two libraries agree in
   magnitude.
5. Every parameter comes from the registry (`core/parameters.py`) with article
   defaults; colormap editor live-updates; ref/target swap flips sign; mirror
   works.
6. `parity-guard` passes: **both** UIs expose the same parameter set + features.
7. Re-run from `config.yaml` reproduces the stats table; **both** frontends
   launch via docker-compose.

## Non-goals / explicit scope limits
- Not a clinical diagnostic. Research tooling only.
- No causal claims from a single subject.
- Treece/Poole density-deconvolution cortical thickness is noted as future work,
  not implemented as the primary method.

## Working method
Small, verified steps behind the phase gates below. TDD (tests first for core
logic). Never fabricate numbers — on failure, stop and report. Log every
parameter/threshold/transform to `config.yaml` + a run log.

## Phase gates (do not skip)
| Phase | Deliverable | Gate |
|---|---|---|
| 0 | Setup, registry, ingest | geometry/laterality/distinct-scan reported |
| 1 | core: segmentation + region labeling + meshing | clean seg; region toggles work |
| 2 | Mode A thickness + measurement + Fig-2 render | methods agree; colorbar matches Fig. 2 |
| 3 | Mode B registration + mirror/swap + signed distance | anchor RMS < threshold; sign verified |
| 4 | Stats + plots | Table-1 + Fig 3/4/5-style outputs |
| 5 | Both UIs from the registry | parity-guard passes |
| 6 | README + dual deploy + reproducibility | re-run reproduces; both launch |

Progress is tracked in `WATCHDOG.md`.
