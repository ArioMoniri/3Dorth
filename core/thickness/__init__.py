"""Cortical thickness: local thickness (primary) + ray-cast validation."""

from core.thickness.thickness import (
    ThicknessAgreement,
    agreement,
    local_thickness_map,
    raycast_thickness_on_vertices,
    sample_scalar_on_vertices,
)

__all__ = [
    "local_thickness_map",
    "raycast_thickness_on_vertices",
    "sample_scalar_on_vertices",
    "agreement",
    "ThicknessAgreement",
]
