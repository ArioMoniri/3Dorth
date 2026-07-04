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
MODE_B_COLORMAPS = ["blue_white_red", "coolwarm", "RdBu_r", "seismic", "bwr"]
AXES = ["x", "y", "z"]
SIGN_CONVENTIONS = ["target_outside_positive", "target_outside_negative"]
STANDARD_VIEWS = ["anterior", "posterior", "lateral", "medial", "superior", "inferior"]
SCAN_ROLES = ["scan_a", "scan_b"]


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
        control=ControlType.INT, default=7, minimum=2, maximum=20, step=1, mode=Mode.A,
        help="Number of discrete legend bands. Paper Fig. 2 uses 7.",
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

    # ---- Meshing ------------------------------------------------------------
    ParamSpec(
        key="mesh_smooth_iters", label="Mesh smoothing iters", group="Meshing",
        control=ControlType.INT, default=20, minimum=0, maximum=200, step=1,
        help="Taubin smoothing iterations (shape-preserving).",
    ),
    ParamSpec(
        key="mesh_decimate_fraction", label="Mesh decimation", group="Meshing",
        control=ControlType.FLOAT, default=0.0, minimum=0.0, maximum=0.95, step=0.05,
        help="Fraction of triangles to remove. 0 = no decimation.",
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


def control_dicts(mode: str | None = None) -> list[dict]:
    """Registry as plain dicts for UI rendering / JSON transport to React."""
    items = REGISTRY if mode is None else registry_for_mode(mode)
    return [p.model_dump(mode="json") for p in items]


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
