"""One-call multi-format export bundle.

:func:`export_bundle` renders/saves a result surface in every requested format
(raster figures, meshes, and/or a de-identified DICOM Secondary Capture) into a
single directory and returns ``{fmt: path}``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from core.export.dicom_sc import export_dicom_secondary_capture
from core.export.figure import export_figure
from core.export.mesh import export_mesh

_RASTER = ("png", "tiff", "jpg")
_MESH = ("stl", "ply", "obj", "vtp", "glb")


def export_bundle(
    mesh, scalar_name, params, out_dir, *,
    formats=("png", "tiff", "stl", "vtp"), dpi: int = 300,
    camera: dict | None = None, diverging: bool = False,
    stem: str = "export",
) -> dict[str, str]:
    """Export ``mesh`` (coloured by ``scalar_name``) to every format in ``formats``.

    Recognised formats: raster ``png`` / ``tiff`` / ``jpg``; meshes ``stl`` /
    ``ply`` / ``obj`` / ``vtp`` / ``glb`` (AR); and ``dicom`` (de-identified
    Secondary Capture).
    Returns a dict mapping each requested format to the saved file path (str).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}

    # Colour bake clim for mesh formats matches the figure colorbar.
    if diverging:
        clim = (params.mode_b_center - params.mode_b_range_abs,
                params.mode_b_center + params.mode_b_range_abs)
        cmap_name = params.mode_b_colormap
    else:
        clim = (params.mode_a_range_min, params.mode_a_range_max)
        cmap_name = params.mode_a_colormap

    want = [f.lower() for f in formats]

    # Render one PNG if any raster or a DICOM SC is requested (reuse the pixels).
    need_raster = [f for f in want if f in _RASTER]
    need_dicom = "dicom" in want
    base_png = None
    if need_raster or need_dicom:
        base_png = out_dir / f"{stem}.png"
        export_figure(mesh, scalar_name, params, base_png, fmt="png",
                      dpi=dpi, camera=camera, diverging=diverging)

    for f in want:
        if f in _RASTER:
            if f == "png":
                saved["png"] = str(base_png)
            else:
                p = out_dir / f"{stem}.{f}"
                export_figure(mesh, scalar_name, params, p, fmt=f, dpi=dpi,
                              camera=camera, diverging=diverging)
                saved[f] = str(p)
        elif f in _MESH:
            p = out_dir / f"{stem}.{f}"
            export_mesh(mesh, p, fmt=f, scalar_name=scalar_name,
                        cmap_name=cmap_name, clim=clim)
            saved[f] = str(p)
        elif f == "dicom":
            rgb = np.asarray(Image.open(base_png).convert("RGB"))
            p = out_dir / f"{stem}.dcm"
            export_dicom_secondary_capture(rgb, p, description="3Dorth export")
            saved["dicom"] = str(p)
        else:
            raise ValueError(f"unknown export format {f!r}")

    return saved
