"""Colormap + figure helpers."""
import numpy as np

import core.parameters as P
from core.viz import FIG2_TICKS, discrete_colors, get_cmap, render_thickness_figure


def test_fig2_ticks_match_article():
    assert len(FIG2_TICKS) == 7
    assert abs(FIG2_TICKS[0] - 0.1537) < 1e-6
    assert abs(FIG2_TICKS[-1] - 6.5202) < 1e-6
    # evenly spaced (as the article's legend is)
    diffs = np.diff(FIG2_TICKS)
    assert np.allclose(diffs, diffs[0], atol=1e-4)


def test_get_cmap_custom_and_builtin():
    assert get_cmap("green_yellow_red") is not None
    assert get_cmap("viridis") is not None
    fwd = discrete_colors("green_yellow_red", 7)
    rev = discrete_colors("green_yellow_red", 7, reverse=True)
    assert fwd.shape == (7, 4)
    assert np.allclose(fwd[0], rev[-1])  # reverse flips ends


def test_render_thickness_figure(tmp_path):
    import pyvista as pv
    from core.meshing import mask_to_mesh

    mask = np.zeros((20, 20, 20), dtype=bool)
    mask[5:15, 5:15, 5:15] = True
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    mesh["thickness_mm"] = np.full(mesh.n_points, 3.0)
    out = render_thickness_figure(mesh, "thickness_mm", P.default_parameters(),
                                  tmp_path / "fig.png")
    assert out.exists() and out.stat().st_size > 5000
