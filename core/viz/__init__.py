"""Visualization: article-faithful colormaps, colorbars, and figure export."""

from core.viz.colormap import (
    FIG2_TICKS,
    discrete_colors,
    fig2_colorbar_ticks,
    get_cmap,
)
from core.viz.figure import render_thickness_figure

__all__ = [
    "FIG2_TICKS",
    "fig2_colorbar_ticks",
    "get_cmap",
    "discrete_colors",
    "render_thickness_figure",
]
