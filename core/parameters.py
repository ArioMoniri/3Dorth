"""Parameter registry — the single source of truth for every configurable knob.

Architecture rule (see CONTRIBUTING.md, "Feature parity"):
  * Every configurable parameter is declared once, here, as a ``ParamSpec``.
  * The runtime ``Parameters`` model is *generated* from ``REGISTRY`` via
    ``pydantic.create_model``, so the model and the registry can never drift.
  * Both frontends (app_trame, app_react) build their control panels by
    iterating ``REGISTRY``. ``tests/unit/test_parity.py`` asserts that each UI
    exposes exactly ``registry_keys()``.

Defaults reproduce Guo et al. 2022, Eur J Med Res 27:102 (see docs/METHOD.md).
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator


class ControlType(str, Enum):
    """How a parameter should be rendered as a UI control."""

    INT = "int"
    FLOAT = "float"
    ENUM = "enum"
    BOOL = "bool"


class Mode(str, Enum):
    """Which analysis mode a parameter applies to."""

    A = "A"  # cortical thickness mapping (single scan)
    B = "B"  # two-scan signed deviation comparison
    BOTH = "both"


class ParamSpec(BaseModel):
    """Declarative description of one configurable parameter / UI control."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    group: str
    control: ControlType
    default: Any
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: list[str] | None = None
    mode: Mode = Mode.BOTH
    help: str = ""


# --- controlled vocabularies (kept as plain lists so the UI can render them) ---

THICKNESS_ALGORITHMS = ["local_thickness", "ray_cast"]
MODE_A_COLORMAPS = ["green_yellow_red", "viridis", "plasma", "inferno", "magma", "turbo", "cividis"]
MODE_B_COLORMAPS = ["blue_white_red", "green_white_red", "coolwarm", "RdBu_r", "seismic", "bwr"]
AXES = ["x", "y", "z"]
SIGN_CONVENTIONS = ["target_outside_positive", "target_outside_negative"]
STANDARD_VIEWS = ["anterior", "posterior", "lateral", "medial", "superior", "inferior"]
SCAN_ROLES = ["scan_a", "scan_b"]
# N-way "compare all visits at once" (same anatomical side) map choices.
NWAY_AGGREGATES = ["baseline_to_latest", "mean_signed", "max_abs_signed"]
NWAY_COLORED = ["latest", "baseline"]
# DISPLAY-ONLY surface reconstruction levels (3-matic-equivalent smooth render).
MESH_RECONSTRUCT_LEVELS = ["raw", "smooth", "wrap"]


# --------------------------------------------------------------------------- #
# THE REGISTRY.  Add a parameter here and it appears in both UIs automatically.
# --------------------------------------------------------------------------- #
REGISTRY: list[ParamSpec] = [
    # ---- Segmentation / thresholds -----------------------------------------
    ParamSpec(
        key="hu_lower", label="HU lower threshold", group="Segmentation",
        control=ControlType.INT, default=226, unit="HU", minimum=-1024, maximum=3000, step=1,
        help="Bone lower bound. Paper default 226. Tunable from the histogram.",
    ),
    ParamSpec(
        key="hu_upper", label="HU upper threshold", group="Segmentation",
        control=ControlType.INT, default=1600, unit="HU", minimum=0, maximum=4000, step=1,
        help="Bone upper bound. Paper default 1600; also excludes most metal.",
    ),
    ParamSpec(
        key="metal_hu_cutoff", label="Metal/hardware HU cutoff", group="Segmentation",
        control=ControlType.INT, default=2000, unit="HU", minimum=1000, maximum=4000, step=10,
        help="Mask voxels above this (streak artifact / implants); the masked fraction is reported.",
    ),
    ParamSpec(
        key="island_min_voxels", label="Min connected-component size", group="Segmentation",
        control=ControlType.INT, default=2000, unit="voxels", minimum=0, maximum=2_000_000, step=100,
        help="Connected components smaller than this are dropped as noise before labeling.",
    ),
    ParamSpec(
        key="resample_iso_voxel", label="Resample isotropic voxel", group="Processing",
        control=ControlType.FLOAT, default=0.0, unit="mm", minimum=0.0, maximum=2.0, step=0.05,
        help="0 = keep native grid (data-driven). Mode B resamples both scans to a common grid.",
    ),

    # ---- Cortical thickness (Mode A) ---------------------------------------
    ParamSpec(
        key="thickness_algorithm", label="Thickness algorithm", group="Cortical thickness",
        control=ControlType.ENUM, default="local_thickness", choices=THICKNESS_ALGORITHMS, mode=Mode.A,
        help="Primary: local thickness (Hildebrand-Ruegsegger, = 3-Matic wall thickness). "
             "Alt: two-surface ray cast (also used as the cross-validator).",
    ),
    ParamSpec(
        key="thickness_min_clamp", label="Thickness min clamp", group="Cortical thickness",
        control=ControlType.FLOAT, default=0.33, unit="mm", minimum=0.0, maximum=5.0, step=0.01, mode=Mode.A,
        help="Values below this are clipped. Paper default 0.33 mm.",
    ),
    ParamSpec(
        key="thickness_max_clamp", label="Thickness max clamp", group="Cortical thickness",
        control=ControlType.FLOAT, default=10.0, unit="mm", minimum=1.0, maximum=30.0, step=0.1, mode=Mode.A,
        help="Values above this are clipped. Paper default 10 mm.",
    ),

    # ---- Mode A coloring ----------------------------------------------------
    ParamSpec(
        key="mode_a_colormap", label="Colormap (Mode A)", group="Coloring",
        control=ControlType.ENUM, default="green_yellow_red", choices=MODE_A_COLORMAPS, mode=Mode.A,
        help="Sequential map. Paper default green->yellow->red.",
    ),
    ParamSpec(
        key="mode_a_colormap_reverse", label="Reverse colormap (Mode A)", group="Coloring",
        control=ControlType.BOOL, default=False, mode=Mode.A,
        help="Flip the direction of the Mode A colormap.",
    ),
    ParamSpec(
        key="mode_a_range_min", label="Colorbar min (Mode A)", group="Coloring",
        control=ControlType.FLOAT, default=0.1537, unit="mm", minimum=0.0, maximum=30.0, step=0.01, mode=Mode.A,
        help="Legend lower bound. Paper Fig. 2 low tick = 0.1537 mm.",
    ),
    ParamSpec(
        key="mode_a_range_max", label="Colorbar max (Mode A)", group="Coloring",
        control=ControlType.FLOAT, default=6.5202, unit="mm", minimum=0.0, maximum=30.0, step=0.01, mode=Mode.A,
        help="Legend upper bound. Paper Fig. 2 high tick = 6.5202 mm.",
    ),
    ParamSpec(
        key="mode_a_colorbar_steps", label="Colorbar steps (Mode A)", group="Coloring",
        control=ControlType.INT, default=7, minimum=2, maximum=64, step=1, mode=Mode.A,
        help="Number of discrete legend bands. Paper Fig. 2 uses 7; raise toward 64 "
             "for a smooth, near-continuous gradient.",
    ),
    ParamSpec(
        key="color_smooth_iters", label="Colour smoothing", group="Coloring",
        control=ControlType.INT, default=0, minimum=0, maximum=20, step=1,
        help="Laplacian smoothing of the DISPLAYED thickness/deviation colour "
             "across the surface — a smoother green→red gradient like the paper "
             "Fig. 2. Display-only: the computed thickness and every statistic "
             "stay on the raw per-vertex values; only the rendered colour is "
             "smoothed (0 = sharp per-vertex colour).",
    ),

    # ---- Measurement tools (Mode A) ----------------------------------------
    ParamSpec(
        key="measure_line_points", label="Line sample points (N)", group="Measurement",
        control=ControlType.INT, default=3, minimum=2, maximum=10, step=1, mode=Mode.A,
        help="Points along the cortical-thickness sampling line. Paper uses 3.",
    ),
    ParamSpec(
        key="height_axis", label="Height/extent axis", group="Measurement",
        control=ControlType.ENUM, default="z", choices=AXES, mode=Mode.A,
        help="Axis along which the height/extent bracket is measured (Z = up).",
    ),
    ParamSpec(
        key="measure_line_frac", label="Sampling-line height", group="Measurement",
        control=ControlType.FLOAT, default=0.15, minimum=0.0, maximum=1.0, step=0.01,
        mode=Mode.A,
        help="Fractional height of the auto-placed Fig-2 cortical-thickness sampling "
             "line along the height axis (0 = proximal base, 1 = top). 0.15 ≈ the "
             "surgical-neck / lesser-tuberosity base. Adjusts export-overlay "
             "PLACEMENT only — the sampled thickness is always read off the computed "
             "map, never fabricated.",
    ),
    ParamSpec(
        key="measure_bracket_lo_frac", label="Height bracket — lower", group="Measurement",
        control=ControlType.FLOAT, default=0.0, minimum=0.0, maximum=1.0, step=0.01,
        mode=Mode.A,
        help="Lower end of the Fig-2 panel-B height bracket, as a fraction of the "
             "axial extent (0 = base). Export-overlay placement only.",
    ),
    ParamSpec(
        key="measure_bracket_hi_frac", label="Height bracket — upper", group="Measurement",
        control=ControlType.FLOAT, default=0.5, minimum=0.0, maximum=1.0, step=0.01,
        mode=Mode.A,
        help="Upper end of the Fig-2 panel-B height bracket, as a fraction of the "
             "axial extent (1 = top). Export-overlay placement only.",
    ),

    # ---- Registration (Mode B) ---------------------------------------------
    ParamSpec(
        key="reg_voxel_size", label="Global reg. voxel size", group="Registration",
        control=ControlType.FLOAT, default=2.0, unit="mm", minimum=0.5, maximum=10.0, step=0.1, mode=Mode.B,
        help="Downsample voxel for FPFH+RANSAC global registration.",
    ),
    ParamSpec(
        key="reg_icp_iters", label="ICP iterations", group="Registration",
        control=ControlType.INT, default=50, minimum=1, maximum=500, step=1, mode=Mode.B,
        help="Max iterations for ICP refinement on the anchor region.",
    ),
    ParamSpec(
        key="anchor_region", label="Anchor region", group="Registration",
        control=ControlType.ENUM, default="auto", choices=["auto"], mode=Mode.B,
        help="Region label that drives the fit. 'auto' uses all visible surface; "
             "the UI repopulates choices with labeled regions after loading.",
    ),
    ParamSpec(
        key="mirror_sagittal", label="Mirror one bone (sagittal)", group="Registration",
        control=ControlType.BOOL, default=False, mode=Mode.B,
        help="Sagittal flip for left/right contralateral comparison. Off by default.",
    ),
    ParamSpec(
        key="mode_b_reference", label="Reference scan", group="Comparison",
        control=ControlType.ENUM, default="scan_a", choices=SCAN_ROLES, mode=Mode.B,
        help="Which scan is the reference. Swapping reference/target flips the deviation sign.",
    ),
    ParamSpec(
        key="signed_distance_sign", label="Signed-distance convention", group="Comparison",
        control=ControlType.ENUM, default="target_outside_positive", choices=SIGN_CONVENTIONS, mode=Mode.B,
        help="target_outside_positive: target surface outside reference = positive (gain/hypertrophy).",
    ),
    # ---- N-way "all visits at once" (same side across series) ---------------
    ParamSpec(
        key="nway_aggregate", label="All-visits map", group="Comparison",
        control=ControlType.ENUM, default="baseline_to_latest", choices=NWAY_AGGREGATES, mode=Mode.B,
        help="When comparing 3+ visits at once: baseline_to_latest = net change (baseline→last, "
             "preserves direction); mean_signed = average signed change; max_abs_signed = largest "
             "|change| at each point. A per-vertex spread (SD across visits) is always available.",
    ),
    ParamSpec(
        key="nway_colored", label="Colour which surface", group="Comparison",
        control=ControlType.ENUM, default="latest", choices=NWAY_COLORED, mode=Mode.B,
        help="Which surface carries the colour map: the latest visit (default) or the baseline. "
             "The other visits are drawn as faint ghost shells.",
    ),

    # ---- Mode B coloring ----------------------------------------------------
    ParamSpec(
        key="mode_b_colormap", label="Colormap (Mode B)", group="Coloring",
        control=ControlType.ENUM, default="blue_white_red", choices=MODE_B_COLORMAPS, mode=Mode.B,
        help="Diverging map. Default blue-white-red.",
    ),
    ParamSpec(
        key="mode_b_center", label="Diverging center (Mode B)", group="Coloring",
        control=ControlType.FLOAT, default=0.0, unit="mm", minimum=-10.0, maximum=10.0, step=0.1, mode=Mode.B,
        help="Deviation value mapped to the neutral (white) color. Default 0.",
    ),
    ParamSpec(
        key="mode_b_range_abs", label="Colorbar |range| (Mode B)", group="Coloring",
        control=ControlType.FLOAT, default=5.0, unit="mm", minimum=0.1, maximum=30.0, step=0.1, mode=Mode.B,
        help="Symmetric limit; colorbar spans [center-range, center+range].",
    ),
    ParamSpec(
        key="mode_b_colorbar_steps", label="Colorbar steps (Mode B)", group="Coloring",
        control=ControlType.INT, default=11, minimum=3, maximum=65, step=2, mode=Mode.B,
        help="Number of discrete diverging bands for the deviation colorbar. Raise "
             "toward 65 for a smooth, near-continuous gradient (finer differences).",
    ),

    # ---- Meshing ------------------------------------------------------------
    ParamSpec(
        key="mesh_smooth_iters", label="Surface (tissue) smoothing", group="Meshing",
        control=ControlType.INT, default=20, minimum=0, maximum=200, step=1,
        help="Taubin smoothing iterations on the bone surface (shape-preserving) — "
             "the main 'tissue' smoothing knob: higher = smoother, glossier surface. "
             "Display only; cortical thickness is computed on the raw mask.",
    ),
    ParamSpec(
        key="mesh_decimate_fraction", label="Mesh decimation", group="Meshing",
        control=ControlType.FLOAT, default=0.0, minimum=0.0, maximum=0.95, step=0.05,
        help="Fraction of triangles to remove. 0 = no decimation.",
    ),
    ParamSpec(
        key="mesh_close_iters", label="Surface hole-fill", group="Meshing",
        control=ControlType.INT, default=1, minimum=0, maximum=4, step=1,
        help="Morphological closing on the bone mask before meshing — bridges "
             "small cortex gaps / partial-volume speckle for a smoother, less "
             "lacy surface (0 = raw/honest; higher = smoother, but can bridge "
             "real porosity). Display only — cortical thickness is still computed "
             "on the raw mask.",
    ),
    ParamSpec(
        key="mesh_supersample", label="Surface supersample", group="Meshing",
        control=ControlType.INT, default=2, minimum=1, maximum=3, step=1,
        help="Resample the voxel staircase away before meshing (1 = raw blocky "
             "voxel surface; 2-3 = smooth sub-voxel surface, the step Mimics/"
             "3-matic do — the biggest driver of a smooth render). Display only — "
             "cortical thickness is computed on the raw mask.",
    ),
    ParamSpec(
        key="mesh_reconstruct", label="Surface reconstruction", group="Meshing",
        control=ControlType.ENUM, default="wrap", choices=MESH_RECONSTRUCT_LEVELS,
        help="3-matic-EQUIVALENT surface finishing for the render. 'raw' = the "
             "marching-cubes shell as-is; 'smooth' = watertight repair (fill holes "
             "+ manifold clean) + windowed-sinc smoothing; 'wrap' (default) = also "
             "isotropic-remesh to an even triangulation and decimate to budget — a "
             "clean, watertight, evenly-triangulated shell (the paper's smooth look). "
             "DISPLAY-ONLY cosmetic mesh: the mask boundary is unchanged and cortical "
             "thickness stays computed on the raw thresholded mask at native spacing, "
             "then re-sampled onto the reconstructed vertices (single-subject, "
             "descriptive).",
    ),
    ParamSpec(
        key="surface_quality", label="Surface quality", group="Meshing",
        control=ControlType.FLOAT, default=1.0, minimum=0.3, maximum=3.0, step=0.1,
        help="Density of the reconstructed ('wrap'/'smooth') surface — a multiplier "
             "on the auto triangle budget. Higher = a finer, higher-quality tissue "
             "surface (more triangles, slower render); lower = lighter. Display-only "
             "cosmetic mesh; cortical thickness is computed on the raw mask.",
    ),

    # ---- Views --------------------------------------------------------------
    ParamSpec(
        key="standardized_view", label="Standardized view", group="Views",
        control=ControlType.ENUM, default="anterior", choices=STANDARD_VIEWS,
        help="Identical camera + lighting preset across bones for comparable figures.",
    ),
]


# --------------------------------------------------------------------------- #
# Registry helpers
# --------------------------------------------------------------------------- #
def registry_keys() -> list[str]:
    """Ordered list of every parameter key. UIs and the parity test use this."""
    return [p.key for p in REGISTRY]


def spec(key: str) -> ParamSpec:
    for p in REGISTRY:
        if p.key == key:
            return p
    raise KeyError(f"Unknown parameter: {key!r}")


def registry_for_mode(mode: str) -> list[ParamSpec]:
    """Specs relevant to a mode ('A' or 'B'), including shared ('both') params."""
    m = Mode(mode)
    return [p for p in REGISTRY if p.mode == m or p.mode == Mode.BOTH]


# Parameters that only affect DISPLAY (applied instantly, client-side: LUT,
# legend, camera) and do NOT need a server recompute. Everything else changes the
# analysis and triggers a (debounced) auto-recompute so edits reflect in realtime.
DISPLAY_ONLY_KEYS: set[str] = {
    "mode_a_colormap", "mode_a_colormap_reverse", "mode_a_range_min",
    "mode_a_range_max", "mode_a_colorbar_steps",
    "mode_b_colormap", "mode_b_center", "mode_b_range_abs", "mode_b_colorbar_steps",
    "standardized_view",
    # colour smoothing is applied at render time (client-side in React, server
    # re-render in trame); it never re-runs the pipeline or changes any statistic.
    "color_smooth_iters",
    # Fig-2 overlay PLACEMENT only affects the exported annotated figure, not the
    # pipeline or the live map — so no recompute is needed when these change.
    "measure_line_frac", "measure_bracket_lo_frac", "measure_bracket_hi_frac",
}


def affects_compute(key: str) -> bool:
    """True if changing this parameter requires re-running the pipeline."""
    return key not in DISPLAY_ONLY_KEYS


def control_dicts(mode: str | None = None) -> list[dict]:
    """Registry as plain dicts for UI rendering / JSON transport to React.

    Each dict carries ``recompute``: True -> the UI auto-recomputes (debounced)
    on change; False -> the change applies instantly client-side (coloring/view).
    """
    items = REGISTRY if mode is None else registry_for_mode(mode)
    out = []
    for p in items:
        d = p.model_dump(mode="json")
        d["recompute"] = affects_compute(p.key)
        out.append(d)
    return out


def _duplicate_keys() -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for k in registry_keys():
        if k in seen:
            dups.append(k)
        seen.add(k)
    return dups


assert not _duplicate_keys(), f"Duplicate parameter keys in REGISTRY: {_duplicate_keys()}"


# --------------------------------------------------------------------------- #
# Parameters model, generated from the registry (never hand-maintained)
# --------------------------------------------------------------------------- #
_PY_TYPE = {
    ControlType.INT: int,
    ControlType.FLOAT: float,
    ControlType.BOOL: bool,
    ControlType.ENUM: str,
}


class _ParametersBase(BaseModel):
    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    @model_validator(mode="after")
    def _validate_against_registry(self):
        for p in REGISTRY:
            val = getattr(self, p.key)
            if p.control in (ControlType.INT, ControlType.FLOAT):
                if p.minimum is not None and val < p.minimum:
                    raise ValueError(f"{p.key}={val} below minimum {p.minimum}")
                if p.maximum is not None and val > p.maximum:
                    raise ValueError(f"{p.key}={val} above maximum {p.maximum}")
            if p.control == ControlType.ENUM and p.choices and val not in p.choices:
                # 'anchor_region' choices are repopulated at runtime; allow any str.
                if p.key != "anchor_region":
                    raise ValueError(f"{p.key}={val!r} not in {p.choices}")
        return self


def _build_parameters_model():
    fields: dict[str, tuple] = {}
    for p in REGISTRY:
        fields[p.key] = (_PY_TYPE[p.control], Field(default=p.default))
    return create_model("Parameters", __base__=_ParametersBase, **fields)


Parameters = _build_parameters_model()
"""Runtime, validated parameter set. ``Parameters()`` == the article defaults."""


def default_parameters() -> "Parameters":
    return Parameters()


def load_parameters(path: str | Path) -> "Parameters":
    """Load the ``parameters:`` block from a config.yaml (missing keys -> defaults)."""
    doc = yaml.safe_load(Path(path).read_text()) or {}
    return Parameters(**(doc.get("parameters", {})))


def save_parameters(params: "Parameters", path: str | Path, extra: dict | None = None) -> None:
    """Write parameters (plus optional provenance) to a YAML file."""
    doc: dict[str, Any] = {"parameters": params.model_dump()}
    if extra:
        doc.update(extra)
    Path(path).write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
