"""Ingest: zip/DICOM -> de-identified series inventory + volume loading."""

from core.ingest.dicom_ingest import (
    DistinctScanResult,
    IngestReport,
    SeriesInfo,
    compare_scans,
    compute_isotropy,
    enumerate_series,
    find_dicom_root,
    ingest_source,
    load_series_volume,
    select_bone_series,
)
from core.ingest.formats import (
    MESH_EXTENSIONS,
    NIFTI_EXTENSIONS,
    is_mesh,
    is_nifti,
    load_mesh_source,
    load_nifti_volume,
)

__all__ = [
    "SeriesInfo",
    "IngestReport",
    "DistinctScanResult",
    "find_dicom_root",
    "enumerate_series",
    "compute_isotropy",
    "ingest_source",
    "load_series_volume",
    "select_bone_series",
    "compare_scans",
    "NIFTI_EXTENSIONS",
    "MESH_EXTENSIONS",
    "is_nifti",
    "is_mesh",
    "load_nifti_volume",
    "load_mesh_source",
]
