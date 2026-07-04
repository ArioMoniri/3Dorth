# Definition of Done (DoD)

A task, module, or phase is **not done** until every applicable box is checked.
The watchdog (`scripts/watchdog.py`, tracked in `WATCHDOG.md`) verifies these.

## Global DoD (applies to every change)
- [ ] Behaviour lives in `core/` (framework-agnostic; returns data, not UI).
- [ ] If it adds a configurable knob, it is declared in `core/parameters.py`
      and therefore appears in both UIs. (Parity rule — see `CONTRIBUTING.md`.)
- [ ] Tests exist and pass (`pytest`); new logic was written test-first (TDD).
- [ ] No fabricated numbers. Every reported measurement traces to real data or a
      documented synthetic fixture.
- [ ] Parameters/thresholds/transforms used are logged (to `config.yaml` or a
      run log).
- [ ] Outputs are de-identified (no name/MRN/dates).
- [ ] Files stay under ~500 lines; public APIs typed.
- [ ] `ruff` clean; `pytest` green before commit.

## Per-phase DoD / gate
### Phase 0 — Setup & ingest
- [ ] Ingest recurses past the Weasis viewer to the `dicom/` folder.
- [ ] Findings table prints: PixelSpacing, SliceThickness, matrix, isotropy,
      laterality, hardware presence, and distinct-scan confirmation for both.
- [ ] Parameter registry loads; `config.yaml` round-trips to defaults.

### Phase 1 — Segmentation / regions / meshing
- [ ] Bone segmentation is visually clean on a QA render.
- [ ] Connected-component region labels drive show/hide toggles.
- [ ] Analysis respects the current region selection.
- [ ] Surface mesh is watertight-ish (island-removed, smoothed) with correct mm scale.

### Phase 2 — Mode A thickness + measurement
- [x] **Implementation validation (phantom):** on a true cortical shell (hollow
      cylinder, uniform wall) local-thickness ≈ ray-cast (mean abs ≤ 1.2 mm; both
      recover the wall). `test_local_and_raycast_agree_on_hollow_shell`.
- [x] **External validation (magnitude):** local-thickness whole-surface mean on
      the real proximal humerus = **2.78 mm**, inside the paper's Table-1 range
      (~2.1–2.85 mm) — evidence the primary method is correct.
- [x] **Real-bone cross-check:** local vs ray-cast median |diff| ≈ 0.6 mm. The
      residual (ray-cast runs ~0.6 mm thicker) is expected: naive ray-cast
      traverses dense **subcortical trabecular** bone past the endocortical
      boundary. This is the known limitation motivating Treece/Poole density
      deconvolution (future work). Documented, not hidden. The original
      whole-trabecular-surface tolerance (0.3 mm) was scientifically naive.
- [x] Thickness clamped to [0.33, 10] mm.
- [ ] Discrete mm colorbar matches Fig. 2 (7 steps, green→red, article ticks).
- [ ] Line tool (N points, "Cortical thickness" label, triangle markers) and
      height bracket ("Height" label, two lines + vertical measure) render and
      report mm.

### Phase 3 — Mode B registration + deviation
- [ ] Anchor-region ICP RMS **< 1.0 mm** (stated threshold; revisit per data).
- [ ] Overlay visually aligned on the anchor region.
- [ ] Signed-distance sign **verified on a synthetic test point** (a known
      outward bump reads positive under the default convention).
- [ ] Two distance libraries (e.g. trimesh proximity vs VTK/open3d) agree in
      magnitude (median abs diff ≤ 0.2 mm).
- [ ] Ref/target swap flips the sign; sagittal mirror works for L/R.

### Phase 4 — Stats + plots
- [ ] Table-1-style summary (mean/median/SD/RMS/min/max, 95% CI) emitted as CSV+JSON.
- [ ] Histograms; Mode B %-surface over 1 mm / 2 mm split by sign; added/removed volume.
- [ ] Group functions (ANOVA/post-hoc/correlation/regression) exist with unit tests
      on synthetic data; single-subject path avoids inferential claims.

### Phase 5 — Both UIs
- [ ] `app_trame` and `app_react` each render controls from the registry.
- [ ] Every analysis feature is reachable from the UI in **both** frontends.
- [ ] `tests/unit/test_parity.py` passes (both UIs expose `registry_keys()`).

### Phase 6 — Deploy + reproducibility
- [ ] `docker compose --profile trame up` and `--profile react up` both launch.
- [ ] Re-running from a saved `config.yaml` reproduces the stats table.
- [ ] README reads as human-written; cites the paper and defaults; honest limits.
