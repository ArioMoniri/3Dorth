"""Surface registration (Mode B): align two bone surfaces.

Pipeline: convert meshes to point clouds with normals, optionally run a coarse
global FPFH+RANSAC fit, then refine with point-to-plane ICP. A PCA-based initial
alignment is used when global registration is disabled or fails. Also provides a
sagittal ``mirror`` for left/right contralateral comparison and an anchor-region
variant that restricts the fit to a chosen subset of the source surface.

All geometry is in world millimetres, vertices ordered (x, y, z).
"""

from core.registration.register import (
    RegistrationResult,
    apply_transform,
    mirror,
    register,
    register_on_anchor,
    to_point_cloud,
)

__all__ = [
    "RegistrationResult",
    "to_point_cloud",
    "register",
    "register_on_anchor",
    "apply_transform",
    "mirror",
]
