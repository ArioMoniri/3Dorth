"""Summary statistics for a signed-deviation field (Mode B).

Aggregates a per-vertex signed distance (mm) into a typed, framework-agnostic
:class:`DeviationStats`. When per-vertex surface areas are supplied, the signed
distance is integrated over area to split the change into an ADDED volume
(positive deviation) and a REMOVED volume (negative deviation), reported in
cubic centimetres.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

_MM3_PER_CC = 1000.0  # 1 cc = 1000 mm^3


class DeviationStats(BaseModel):
    """Typed summary of a signed-deviation field (all distances in mm)."""

    n: int
    mean: float
    median: float
    sd: float
    rms: float
    max_positive: float
    max_negative: float
    pct_over_1mm_pos: float
    pct_over_1mm_neg: float
    pct_over_2mm_pos: float
    pct_over_2mm_neg: float
    added_volume_cc: float
    removed_volume_cc: float


def deviation_stats(
    dev: np.ndarray,
    areas: np.ndarray | None = None,
    region_labels: np.ndarray | None = None,
) -> DeviationStats:
    """Summarise a signed-deviation field.

    ``dev`` is one signed distance (mm) per vertex. ``areas`` is the matching
    per-vertex area (mm^2); when given, ``added_volume_cc`` integrates the
    positive deviations over area and ``removed_volume_cc`` integrates the
    magnitude of the negative deviations (reported as a positive number).
    ``region_labels`` restricts the summary to vertices whose label is truthy
    (e.g. a boolean anatomical mask); it never changes the sign convention.
    """
    dev = np.asarray(dev, dtype=np.float64).ravel()
    finite = np.isfinite(dev)

    if region_labels is not None:
        region = np.asarray(region_labels).ravel().astype(bool)
        if region.shape != dev.shape:
            raise ValueError("region_labels must match dev length")
        finite &= region

    d = dev[finite]
    if areas is not None:
        a = np.asarray(areas, dtype=np.float64).ravel()
        if a.shape != dev.shape:
            raise ValueError("areas must match dev length")
        a = a[finite]
    else:
        a = None

    if d.size == 0:
        return DeviationStats(
            n=0, mean=0.0, median=0.0, sd=0.0, rms=0.0,
            max_positive=0.0, max_negative=0.0,
            pct_over_1mm_pos=0.0, pct_over_1mm_neg=0.0,
            pct_over_2mm_pos=0.0, pct_over_2mm_neg=0.0,
            added_volume_cc=0.0, removed_volume_cc=0.0,
        )

    n = int(d.size)
    pos = d[d > 0]
    neg = d[d < 0]

    def _pct(mask: np.ndarray) -> float:
        return 100.0 * float(np.count_nonzero(mask)) / n

    if a is not None:
        added_mm3 = float(np.sum(np.clip(d, 0.0, None) * a))
        removed_mm3 = float(np.sum(np.clip(-d, 0.0, None) * a))
    else:
        added_mm3 = removed_mm3 = 0.0

    return DeviationStats(
        n=n,
        mean=float(np.mean(d)),
        median=float(np.median(d)),
        sd=float(np.std(d)),
        rms=float(np.sqrt(np.mean(d**2))),
        max_positive=float(pos.max()) if pos.size else 0.0,
        max_negative=float(neg.min()) if neg.size else 0.0,
        pct_over_1mm_pos=_pct(d > 1.0),
        pct_over_1mm_neg=_pct(d < -1.0),
        pct_over_2mm_pos=_pct(d > 2.0),
        pct_over_2mm_neg=_pct(d < -2.0),
        added_volume_cc=added_mm3 / _MM3_PER_CC,
        removed_volume_cc=removed_mm3 / _MM3_PER_CC,
    )


def deviation_histogram(
    dev: np.ndarray,
    n_bins: int = 40,
    value_range: tuple[float, float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Histogram of the signed-deviation field.

    Returns ``(bin_edges, counts)`` where ``bin_edges`` has ``n_bins + 1``
    entries. When ``value_range`` is omitted a symmetric range about zero is used
    so the diverging Mode-B colouring stays centred.
    """
    d = np.asarray(dev, dtype=np.float64).ravel()
    d = d[np.isfinite(d)]
    if value_range is None:
        m = float(np.max(np.abs(d))) if d.size else 1.0
        m = m if m > 0 else 1.0
        value_range = (-m, m)
    counts, edges = np.histogram(d, bins=n_bins, range=value_range)
    return edges, counts
