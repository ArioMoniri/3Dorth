# Method and reproduced defaults

## Reference
Guo J, Zhou Y, Shang M, Chen W, Hou Z, Zhang Y, Dong W. **Morphological
characteristics of the surgical neck region in the proximal humerus at different
ages.** *European Journal of Medical Research* 2022;27:102.
doi:10.1186/s40001-022-00724-w. Trial NCT04523415. Open Access (CC BY 4.0).

The paper builds a 3D cortical-thickness map of the proximal-humerus **surgical
neck region (SNR)** with **Mimics 21.0** (segmentation) and **3-Matic 12.0**
(wall-thickness analysis), and studies how cortical thickness and the "cortical
change region" height vary with age. This project reproduces that pipeline with
open-source tools and generalizes it to arbitrary bones and to two-scan
comparison.

## Reproduced defaults (verbatim from the paper)
Every value below is confirmed against the source and encoded as a default in
`core/parameters.py`.

| Quantity | Paper value | Source (paper) | Registry key |
|---|---|---|---|
| HU lower threshold | **226** | "Housfield units of 1600 (maximum) and 226 (minimum) ... upper and lower threshold of the bone" | `hu_lower` |
| HU upper threshold | **1600** | same sentence | `hu_upper` |
| Cortical thickness min | **0.33 mm** | "The minimum threshold was identified as 0.33 mm" | `thickness_min_clamp` |
| Cortical thickness max | **10 mm** | "the maximum thickness was 10 mm" | `thickness_max_clamp` |
| Thickness tool | 3-Matic **wall thickness** | "measured with the function of the wall thickness analysis tool" | `thickness_algorithm=local_thickness` |
| CT resolution | **1 mm slices** | "the image matrix size was same (1 mm slices)" | (data-driven) |
| Measurement line | **3 points** below lesser tuberosity | "Three different points were chosen: adjacent to the bicipital groove (anterolateral), middle of the greater tuberosity, and posterolateral point" | `measure_line_points` |
| Valid height | min height of same-color region | "Valid height represents the minimum height of the cortical change region with same color (cortical thickness)" | `height_axis` + bracket tool |
| Fig-2 colorbar ticks (mm) | 0.1537, 1.2148, 2.2759, 3.3370, 4.3980, 5.4591, 6.5202 | Fig. 2 legend | `mode_a_range_min/max`, `mode_a_colorbar_steps=7` |
| Colormap | green (low) -> yellow -> red (high) | Fig. 2 | `mode_a_colormap=green_yellow_red` |

## Cortical thickness algorithm
1. **Primary — local thickness (Hildebrand & Rüegsegger).** The largest-inscribed-
   sphere thickness on the cortical mask; this is what 3-Matic's wall-thickness
   tool computes. Implementation: EDT-based local thickness (`scipy.ndimage`
   distance transform, or `porespy`/`localthickness`), in mm, clamped to
   [0.33, 10] mm, sampled onto the **outer** surface vertices (trilinear).
2. **Validation — two-surface ray casting.** Outer + inner (endocortical)
   surfaces; cast inward along vertex normals; thickness = hit distance.
   Cross-checked against method 1; agreement reported (see DoD tolerance).
3. Treece/Poole density-deconvolution (the gold standard for sub-voxel cortices)
   is noted as **future work**, not implemented.

## Sign and orientation conventions
- **Mode B signed distance:** `+` = target surface **outside** the reference
  (bone gain / hypertrophy). Swapping reference/target flips the sign. The sign
  is verified on a synthetic test point in `tests/` before any real result is
  reported.
- **Axes:** Z up, X right, Y per the paper's triad. Standardized views
  (anterior/posterior/lateral/medial/superior) use identical camera + lighting.

## Statistics reproduced (as reusable functions)
One-way ANOVA + post-hoc (Tukey / Student-Newman-Keuls), paired t / Wilcoxon,
Spearman/Pearson correlation, linear + nonlinear regression with fitted equation
and R². For a single subject the tool presents descriptive maps + magnitudes and
does **not** run group inference (avoids over-claiming).

Paper Table 1 (used as a sanity reference for the summary functions):

| Age group | Cortical thickness mm (95% CI) | Height mm (95% CI) |
|---|---|---|
| 19–30 | 2.85 (2.67, 3.04) | 8.02 (6.75, 9.29) |
| 31–40 | 2.48 (2.32, 2.64) | 5.77 (4.82, 6.72) |
| 41–50 | 2.33 (2.07, 2.58) | 5.04 (4.27, 5.82) |
| 51–60 | 2.09 (1.90, 2.22) | 5.95 (5.13, 6.75) |
| >60 | 2.08 (2.22, 2.40) | 7.45 (6.86, 8.05) |

Regressions: cortical thickness `y = -0.01533·age + 3.69` (r = -0.5481);
height `y = 0.003921·age² - 0.3687·age + 14.19` (r² = 0.1435).
