# WATCHDOG — living verification ledger

The watchdog is the project's independent verifier. It trusts nothing that is
not checked. Automated checks live in `scripts/watchdog.py` (run:
`.venv/bin/python scripts/watchdog.py`). This file is the human-readable ledger:
every acceptance criterion maps to a **verification method** and a **status**.

Status key: ✅ done+verified · 🟡 in progress · ⬜ not started · ⚠️ blocked

## Phase gates
| Phase | Gate | Verify by | Status |
|---|---|---|---|
| 0 | Ingest recurses to `dicom/`; findings table (geometry/laterality/hardware/distinct) | `pytest tests/unit/test_ingest.py` (14 pass); ran `scripts/ingest_report.py` | ✅ |
| 0 | Registry loads; config round-trips | watchdog check `registry`, `config_roundtrip` | ✅ |

### Phase 0 findings of record (see outputs/phase0_ingest.json)
- The two ZIPs are the **same** study (patient_hash `1919df63`, identical primary SeriesInstanceUID) — the `(1)` file is a duplicate. **Not** two separate scans.
- Single **bilateral** shoulder CT ("L+R OMUZ"): bone-kernel axial (195 sl, 0.977×0.977×1.25 mm), soft-tissue axial, 0.977 mm isotropic sagittal (493) / coronal (275) reformats, plus scout/dose/derived.
- Trace high-density voxels (HU max 3071, ~2.5e-5 fraction > 2000 HU) — possible small suture anchor or ceiling saturation; flagged, not a large implant.
- **Blocked-until-asked (Phase 3):** operated side unknown (no laterality tag). Mode B will split the bilateral volume into L/R halves; confirm operated side with the user then.
- **Phase 1 refinement:** prefer the native **axial bone-kernel** series for segmentation (primary_series heuristic currently picks the largest reformat); make series user-selectable.
| 1 | Clean bone segmentation; region labels drive selection | `test_segmentation.py` (4 pass) + real QA render (`scripts/qa_segment.py`) | ✅ |
| 1 | Mesh in mm, island-removed, smoothed | `test_meshing.py` (3 pass) + real mesh 438k pts | ✅ |
| 1 | UI region show/hide toggles + highlight | deferred to Phase 5 (labels + `combined_mask()` ready; render proves highlight) | ⬜ |

### Phase 1 findings of record (see outputs/phase1_regions.png)
- Bone segmentation is anatomically clean (spine, ribs, sternum, both scapulae, clavicles, both humeri visible).
- Connected-components does NOT isolate a single proximal humerus: at 226 HU the thoracic skeleton is one connected mass. The **left humerus is isolated** (region 4, abducted arm); the **right humerus is fused into the thorax** (adducted arm).
- Non-bone table/positioning pads (>226 HU) appear as regions 2-3 — filtered via region toggles / clipping (both speced).
- **Consequence:** isolating the right proximal humerus (or the SNR sub-region) needs the interactive **clip box / plane** tool (Phase 1 interactivity / Phase 2), not CC labeling alone. Left humerus (region 4) is analysis-ready for the Mode A demo.
| 2 | local-thickness ≈ ray-cast on phantom; magnitude matches paper | `test_thickness.py` (5 pass, incl. hollow-shell phantom); real mean 2.78 mm ∈ paper 2.1–2.85 | ✅ |
| 2 | Fig-2 discrete mm colorbar (7 steps, green→red, article ticks) | `scripts/qa_thickness.py` render (outputs/phase2_thickness.png) | ✅ |
| 2 | Line (N pts) + height bracket overlays, mm readouts | `test_measurement.py` (measurement tools) | ⬜ |

### Phase 2 findings of record (see outputs/phase2_thickness.png + _stats.json)
- Local thickness (Hildebrand-Rüegsegger, = 3-Matic wall thickness) is the primary method. Fig-2-faithful render: thin green cortex on the head, thick orange-red on the diaphysis — correct proximal→distal gradient.
- **Bug caught by the phantom test:** trilinear sampling of the thickness field at surface vertices averaged with background zeros and halved the reading (mean 1.5→2.78 mm after fixing via background extrapolation). Whole-surface mean now matches the paper.
- Ray-cast validator agrees exactly on a shell; on real bone it runs ~0.6 mm thicker in subcortical trabecular regions (expected; motivates Treece — future work).
- Remaining Phase 2 work: Fig-2 measurement overlays (3-point line + height bracket).
| 3 | Anchor ICP RMS < 1.0 mm; overlay aligned | `test_registration.py` | ⬜ |
| 3 | Signed-distance sign verified on synthetic point | `test_deviation_sign.py` | ⬜ |
| 3 | Two distance libs agree (median abs ≤ 0.2 mm) | `test_deviation_agreement.py` | ⬜ |
| 4 | Table-1 summary CSV+JSON; histograms; %>1/2 mm; volume | `test_stats.py` | ⬜ |
| 5 | Parity: both UIs' control source == registry | `test_parity.py` (4 pass; API `/api/parameters` + trame both == registry) | ✅ |
| 5 | Frontend 1 (trame) renders controls from registry + viewport | app constructs (27 controls); scene renders Fig-2 map from VTP bundle | ✅ |
| 5 | Frontend 2 (React + vtk.js) at parity | building against the API contract | 🟡 |
| 5 | Both frontends launch + every feature reachable | manual launch check | ⬜ |
| 6 | Both frontends launch via compose; re-run reproduces stats | manual + `test_reproducibility.py` | ⬜ |

## Standing invariants (checked every run)
| Invariant | Verify by | Status |
|---|---|---|
| No patient PHI in tracked files / outputs | watchdog `deidentify` scan (no "RESIT"/"ENGINAR") | ✅ |
| Patient ZIPs never staged in git | watchdog `git_phi` check | ✅ |
| `config.yaml` == article defaults on fresh load | watchdog `config_roundtrip` | ✅ |
| Sign conventions asserted before any Mode B result | `test_deviation_sign.py` | ⬜ |
| Every reported number traces to data/fixture | code review + watchdog `no_fabrication` note | 🟡 |

## How the watchdog challenges
- It re-derives, it does not re-read a claim. "Tests pass" means it ran them.
- A gate flips to ✅ only when its named verification actually executes green.
- On any red, downstream phases stay ⬜ — no building on an unverified base.

## Progress log — full-build sweep
- **Phase 2 measurement** ✅ `core/measurement` (Fig-2 line + height/valid-height); 8 tests.
- **Phase 3 registration** ✅ `core/registration` (FPFH+RANSAC→ICP, PCA fallback, mirror); 9 tests recover known transforms.
- **Phase 3 deviation** ✅ `core/deviation` (signed distance sign-verified on concentric spheres; vtk↔trimesh cross-check; stats). ⚠️ **Real left-vs-right Mode B is not yet meaningful**: the adducted right humerus is thorax-fused, so auto-isolation picks the wrong structure (inlier ~7.5%). Needs the UI clip/region-select to isolate before the comparison is valid — documented, not hidden.
- **Phase 4 stats** ✅ `core/stats` (Table-1+CI, ANOVA/Tukey/SNK, paired, correlation, linear/nonlinear regression, Fig 3/4/5); 16 tests. Real-data descriptive report: `scripts/stats_report.py` → thickness-by-zone CSV + Fig 4/5 (single-subject, no inference claimed).
- **Interactive backend** ✅ `core/pipeline` + `api/routers/session` (compute-on-demand). Verified: changing HU/algorithm changes the result (3.51 mm → 1.85 mm). This is the fix for "side-panel changes don't apply".
- **Phase 5 UIs** 🟡 both frontends reworked to compute-on-demand (side selector, Apply/Recompute, Mode B thickness+deviation, upload); parity maintained (controls from registry). Final build/run verification pending.
- **Phase 6 deploy** ✅ Dockerfiles + compose profiles + `deploy.sh` one-liner + README/LICENSE. Backend image builds (linux/amd64; open3d has no arm64 wheel). Full compose up + reproducibility re-run: pending final verification.
- Total tests: 80+ pass; watchdog GREEN on the built surface.
