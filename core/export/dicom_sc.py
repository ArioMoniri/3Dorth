"""De-identified DICOM Secondary Capture export.

Wraps a rendered RGB image as a DICOM Secondary Capture (SC) object so a report
figure can be pushed to a PACS. **De-identified by construction**: no patient
name, ID, or dates are ever written — only the pixels, the minimum SC attributes,
and a free-text description are stored.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (
    ExplicitVRLittleEndian,
    SecondaryCaptureImageStorage,
    generate_uid,
)

# Tags that would carry PHI — explicitly kept empty / absent.
_PHI_TAGS = (
    "PatientName", "PatientID", "PatientBirthDate", "PatientSex",
    "StudyDate", "SeriesDate", "AcquisitionDate", "ContentDate",
    "StudyTime", "SeriesTime", "AcquisitionTime",
    "InstitutionName", "ReferringPhysicianName", "AccessionNumber",
)


def export_dicom_secondary_capture(
    image_rgb_uint8: np.ndarray, out_path, *, description: str = "3Dorth export"
) -> Path:
    """Write an RGB image as a de-identified DICOM Secondary Capture.

    ``image_rgb_uint8`` is an ``(H, W, 3)`` uint8 array. The result carries no
    patient name / ID / birth-date / study dates — only the pixels and a
    ``SeriesDescription`` / ``ImageComments`` set to ``description``.
    """
    img = np.asarray(image_rgb_uint8)
    if img.ndim != 3 or img.shape[2] != 3:
        raise ValueError(f"expected (H, W, 3) RGB uint8, got shape {img.shape}")
    img = np.ascontiguousarray(img.astype(np.uint8))
    rows, cols = int(img.shape[0]), int(img.shape[1])

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    fm.MediaStorageSOPInstanceUID = generate_uid()
    fm.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = fm
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "OT"  # "Other"
    ds.ConversionType = "WSD"  # Workstation-derived
    ds.SeriesDescription = description
    ds.ImageComments = description

    # De-identification: explicitly blank/absent PHI. (PatientName/ID left empty
    # so viewers show "anonymous"; date/time tags are simply never set.)
    ds.PatientName = ""
    ds.PatientID = ""
    ds.PatientIdentityRemoved = "YES"
    ds.DeidentificationMethod = "3Dorth secondary-capture export (no PHI written)"

    # Pixel module (RGB, 8-bit).
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "RGB"
    ds.PlanarConfiguration = 0
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = img.tobytes()

    ds.save_as(str(out_path), enforce_file_format=True)

    # Defensive re-read to guarantee no PHI leaked into the written file.
    written = pydicom.dcmread(str(out_path))
    for tag in _PHI_TAGS:
        val = getattr(written, tag, "")
        if val:  # non-empty -> reject
            raise AssertionError(f"PHI tag {tag} present in export: {val!r}")
    return out_path
