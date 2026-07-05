"""Resolve Fig-2 A/B annotation overlays for the exported figure.

The caller passes a small ``annotate`` dict (see :func:`plan_annotations`) and
this module turns it into concrete overlay geometry — the panel-A cortical-
thickness **sampling line** (poly-line + triangular markers) and the panel-B
**height bracket** — placed either at caller-specified coordinates or, by
default, **auto-placed at the surgical-neck / lesser-tuberosity base** like the
paper's Fig-2.

Everything here is world-millimetre, array-oriented (world = idx*spacing +
offset) geometry: NO radiological A/P/S/I. The sampled values are read straight
off the computed per-vertex scalar (cortical thickness, native spacing) — we
NEVER fabricate a measurement; auto-placement only chooses *where* the line/
bracket sits, not what it reads.

The result is descriptive / single-subject: it annotates one exported surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pyvista as pv

from core.measurement.height import HeightMeasurement, measure_height, valid_height
from core.measurement.line import (
    LinePoint,
    sample_line_on_surface,
    sample_line_overlay,
)

_AXIS = {"x": 0, "y": 1, "z": 2}

# Where along the height axis the auto-placed sampling line sits, as a fraction
# of the bone's axial extent measured up from the base. 0.15 ≈ the surgical-neck
# / lesser-tuberosity base level in Fig-2 (just above the proximal-most extent).
_BASE_LINE_FRAC = 0.15


@dataclass
class AnnotationOverlays:
    """Resolved overlay geometry + labels + the read-back measurements.

    ``line_markers`` / ``line`` are pyvista overlays for the sampling line;
    ``bracket`` is the height overlay. ``line_points`` are the sampled
    :class:`LinePoint` values (never fabricated); ``height`` is the
    :class:`HeightMeasurement`. ``captions`` collects the Fig-2 caption strings
    ("Cortical thickness", "Height") for the panels that were drawn.
    """

    line_markers: pv.PolyData | None = None
    line: pv.PolyData | None = None
    line_points: list[LinePoint] = field(default_factory=list)
    bracket: pv.PolyData | None = None
    height: HeightMeasurement | None = None
    captions: list[str] = field(default_factory=list)

    @property
    def any(self) -> bool:
        return self.line is not None or self.bracket is not None


def _as_opts(spec) -> dict:
    """Normalise a per-panel spec: ``True`` -> ``{}`` (auto), dict -> itself."""
    if spec is True:
        return {}
    if isinstance(spec, dict):
        return dict(spec)
    return {}


def _auto_base_span(
    mesh: pv.PolyData,
    axis: str,
    line_frac: float = _BASE_LINE_FRAC,
    lo_frac: float = 0.0,
    hi_frac: float = 0.5,
):
    """(lo, hi) along ``axis`` for the base band, plus the base-line + bracket coords.

    ``lo``/``hi`` are the axial extent. ``line_coord`` = the sampling-line height
    (``line_frac`` up from the base). ``band_lo``/``band_hi`` bound the height
    bracket (``lo_frac``/``hi_frac`` of the extent) — by default the proximal half
    where the surgical-neck / lesser-tuberosity sits. All fractions are user-
    adjustable (registry) so the overlays can be re-placed without recompute.
    """
    ai = _AXIS[axis]
    pts = np.asarray(mesh.points, dtype=np.float64)
    lo = float(pts[:, ai].min())
    hi = float(pts[:, ai].max())
    span = hi - lo
    line_coord = lo + float(line_frac) * span
    band_lo = lo + float(lo_frac) * span
    band_hi = lo + float(hi_frac) * span
    return lo, hi, line_coord, band_lo, band_hi


def _auto_line_endpoints(mesh: pv.PolyData, axis: str, line_frac: float = _BASE_LINE_FRAC):
    """Endpoints of an auto-placed sampling line across the base of the bone.

    The line runs along the widest cross-axis at the sampling-line level
    (``line_frac`` up the axial extent), spanning the bone's extent on that axis
    so its samples cross the cortical wall.
    """
    ai = _AXIS[axis]
    others = [i for i in (0, 1, 2) if i != ai]
    pts = np.asarray(mesh.points, dtype=np.float64)
    _lo, _hi, line_coord, _band_lo, _band_hi = _auto_base_span(mesh, axis, line_frac)

    # pick the wider of the two cross-axes to span (more informative section).
    spans = [(float(pts[:, o].max() - pts[:, o].min()), o) for o in others]
    spans.sort(reverse=True)
    long_axis = spans[0][1]
    mid_axis = spans[1][1]

    p0 = [0.0, 0.0, 0.0]
    p1 = [0.0, 0.0, 0.0]
    p0[ai] = p1[ai] = line_coord
    p0[mid_axis] = p1[mid_axis] = float(np.median(pts[:, mid_axis]))
    p0[long_axis] = float(pts[:, long_axis].min())
    p1[long_axis] = float(pts[:, long_axis].max())
    return tuple(p0), tuple(p1)


def plan_annotations(
    mesh: pv.PolyData,
    scalar_name: str,
    annotate: dict | None,
    params,
    marker_size: float | None = None,
) -> AnnotationOverlays:
    """Build overlay geometry for the requested Fig-2 annotations.

    ``annotate`` keys (both optional):

    * ``sampling_line`` (panel A): ``True`` for the auto-placed line, or a dict
      ``{p0?, p1?, n?}``. ``p0``/``p1`` are world-mm endpoints (default: auto-
      placed across the surgical-neck / lesser-tuberosity base); ``n`` is the
      sample count (default ``params.measure_line_points``).
    * ``height`` (panel B): ``True`` for the auto-placed bracket, or a dict
      ``{axis?, lower?, upper?, band?}``. With ``band=(lo,hi)`` the *minimum
      same-color region height* (``valid_height``) is used; otherwise the axial
      extent between ``lower``/``upper`` (default: the base band).

    Sampled thickness values come straight from ``mesh.point_data[scalar_name]``
    — never fabricated. Returns an :class:`AnnotationOverlays`.
    """
    out = AnnotationOverlays()
    if not annotate:
        return out
    if mesh is None or mesh.n_points == 0:
        return out

    axis_default = getattr(params, "height_axis", "z")
    # Adjustable auto-placement fractions (registry; export-overlay placement only).
    line_frac = float(getattr(params, "measure_line_frac", _BASE_LINE_FRAC))
    lo_frac = float(getattr(params, "measure_bracket_lo_frac", 0.0))
    hi_frac = float(getattr(params, "measure_bracket_hi_frac", 0.5))
    # a modest marker size relative to the mesh so triangles read at any scale.
    if marker_size is None:
        diag = float(np.linalg.norm(np.ptp(np.asarray(mesh.bounds).reshape(3, 2), axis=1)))
        marker_size = max(diag * 0.012, 1e-6)

    # ---- panel A: cortical-thickness sampling line -------------------------- #
    if "sampling_line" in annotate and annotate["sampling_line"]:
        opts = _as_opts(annotate["sampling_line"])
        if scalar_name in getattr(mesh, "point_data", {}):
            axis = str(opts.get("axis", axis_default))
            if axis not in _AXIS:
                axis = "z"
            p0 = tuple(opts["p0"]) if opts.get("p0") is not None else None
            p1 = tuple(opts["p1"]) if opts.get("p1") is not None else None
            if p0 is None or p1 is None:
                ap0, ap1 = _auto_line_endpoints(mesh, axis, line_frac)
                p0 = p0 or ap0
                p1 = p1 or ap1
            n = int(opts.get("n", getattr(params, "measure_line_points", 3)))
            pts = sample_line_on_surface(mesh, scalar_name, p0, p1, n=max(n, 1))
            markers, line, label = sample_line_overlay(pts, marker_size=marker_size)
            out.line_markers = markers
            out.line = line
            out.line_points = pts
            out.captions.append(label)

    # ---- panel B: height / extent bracket ----------------------------------- #
    if "height" in annotate and annotate["height"]:
        opts = _as_opts(annotate["height"])
        axis = str(opts.get("axis", axis_default))
        if axis not in _AXIS:
            axis = "z"
        band = opts.get("band")
        if band is not None and scalar_name in getattr(mesh, "point_data", {}):
            hm = valid_height(mesh, scalar_name, band=(float(band[0]), float(band[1])),
                              axis=axis)
        else:
            lower = opts.get("lower")
            upper = opts.get("upper")
            if lower is None and upper is None:
                # auto: bracket the (adjustable) base band like Fig-2 panel B.
                _lo, _hi, _line, band_lo, band_hi = _auto_base_span(
                    mesh, axis, line_frac, lo_frac, hi_frac
                )
                lower, upper = band_lo, band_hi
            hm = measure_height(mesh, axis=axis,
                                lower=None if lower is None else float(lower),
                                upper=None if upper is None else float(upper))
        out.bracket = hm.overlay
        out.height = hm
        out.captions.append(hm.label)

    return out
