"""Export: multi-format output of a result surface.

* :func:`export_figure` — coloured render + discrete colorbar as png / tiff / jpg
  (TIFF embeds DPI), with an optional camera pose-adjuster.
* :func:`export_mesh` — the surface as stl / ply / obj / vtp (scalars carried
  where the format allows).
* :func:`export_dicom_secondary_capture` — a de-identified DICOM Secondary
  Capture (no PHI).
* :func:`export_bundle` — all of the above in one call, returning ``{fmt: path}``.
"""

from core.export.bundle import export_bundle
from core.export.dicom_sc import export_dicom_secondary_capture
from core.export.figure import export_figure
from core.export.mesh import export_mesh

__all__ = [
    "export_figure",
    "export_mesh",
    "export_dicom_secondary_capture",
    "export_bundle",
]
