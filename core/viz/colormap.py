"""Colormaps and colorbar conventions.

Mode A default reproduces the paper's Fig. 2: a sequential green (low) ->
yellow -> red (high) map with a 7-step discrete legend labelled in mm at
0.1537, 1.2148, 2.2759, 3.3370, 4.3980, 5.4591, 6.5202. Mode B default is a
diverging blue-white-red centred at 0.
"""

from __future__ import annotations

import numpy as np
from matplotlib.colors import Colormap, LinearSegmentedColormap

# The article's Fig. 2 legend ticks (mm), green at the bottom -> red at the top.
FIG2_TICKS = [0.1537, 1.2148, 2.2759, 3.3370, 4.3980, 5.4591, 6.5202]

# Custom maps keyed by the registry's colormap names.
_GREEN_YELLOW_RED = LinearSegmentedColormap.from_list(
    "green_yellow_red",
    ["#0a8f2e", "#7bcf3a", "#e6e600", "#f7a800", "#e60000"],  # green->yellow->red
)
_BLUE_WHITE_RED = LinearSegmentedColormap.from_list(
    "blue_white_red", ["#2166ac", "#f7f7f7", "#b2182b"],  # diverging
)

_CUSTOM = {
    "green_yellow_red": _GREEN_YELLOW_RED,
    "blue_white_red": _BLUE_WHITE_RED,
}


def get_cmap(name: str, reverse: bool = False) -> Colormap:
    """Resolve a registry colormap name to a matplotlib Colormap.

    Custom names ('green_yellow_red', 'blue_white_red') map to the article
    schemes; anything else is looked up as a matplotlib builtin (viridis,
    plasma, coolwarm, RdBu_r, ...).
    """
    if name in _CUSTOM:
        cmap = _CUSTOM[name]
    else:
        import matplotlib as mpl

        cmap = mpl.colormaps[name]
    return cmap.reversed() if reverse else cmap


def fig2_colorbar_ticks(vmin: float = FIG2_TICKS[0], vmax: float = FIG2_TICKS[-1],
                        steps: int = 7) -> list[float]:
    """Evenly spaced legend ticks over [vmin, vmax] (default reproduces Fig. 2)."""
    return list(np.linspace(vmin, vmax, steps))


def discrete_colors(name: str, steps: int, reverse: bool = False) -> np.ndarray:
    """``steps`` RGBA band colors for a discrete legend, as an (steps, 4) array."""
    cmap = get_cmap(name, reverse)
    return cmap(np.linspace(0.0, 1.0, steps))
