"""Deviation: signed surface deviation (Mode B core, safety-critical sign)."""

from core.deviation.distance import cross_check, signed_distance
from core.deviation.figure import deviation_figure
from core.deviation.stats import (
    DeviationStats,
    deviation_histogram,
    deviation_stats,
)

__all__ = [
    "signed_distance",
    "cross_check",
    "DeviationStats",
    "deviation_stats",
    "deviation_histogram",
    "deviation_figure",
]
