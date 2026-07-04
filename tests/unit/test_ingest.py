"""Ingest tests: synthetic (always) + real patient CT (skipped if absent)."""
from pathlib import Path

import numpy as np
import pydicom
import pytest
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from core.ingest import (
    SeriesInfo,
    compare_scans,
    compute_isotropy,
    enumerate_series,
    find_dicom_root,
    ingest_source,
    select_bone_series,
)

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "Bilateral Omuz BT Jul 4 2026"
ZIPS = sorted(DATA_DIR.glob("*.zip")) if DATA_DIR.exists() else []


# --------------------------- synthetic helpers ---------------------------- #
def _write_ct_slice(path: Path, series_uid: str, inst: int, laterality: str,
                    px=(0.5, 0.5), thickness=1.0, z=0.0):
    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = CTImageStorage
    fm.MediaStorageSOPInstanceUID = generate_uid()
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = fm
    ds.SOPClassUID = CTImageStorage
    ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
    ds.Modality = "CT"
    ds.PatientID = "PHANTOM-1"
    ds.SeriesInstanceUID = series_uid
    ds.StudyInstanceUID = "study-1"
    ds.SeriesDescription = f"shoulder {laterality}"
    ds.ImageLaterality = "R" if laterality == "right" else "L"
    ds.InstanceNumber = inst
    ds.Rows, ds.Columns = 8, 8
    ds.PixelSpacing = list(px)
    ds.SliceThickness = thickness
    ds.ImagePositionPatient = [0.0, 0.0, z]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.RescaleIntercept = -1024
    ds.RescaleSlope = 1
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelData = (np.full((8, 8), 500, dtype=np.int16)).tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), enforce_file_format=True)


def _make_weasis_like(root: Path, laterality="right", n=3):
    """Mimic the sample archive layout: viewer junk + a real dicom/ folder."""
    (root / "weasis" / "bundle-i18n").mkdir(parents=True)
    (root / "weasis" / "bundle-i18n" / "viewer.jar").write_bytes(b"not dicom")
    (root / "__MACOSX").mkdir(parents=True)
    (root / "__MACOSX" / "._x").write_bytes(b"junk")
    uid = generate_uid()
    for i in range(n):
        _write_ct_slice(root / "dicom" / "S1" / f"IM{i}.dcm", uid, i + 1, laterality, z=float(i))
    return uid


# ------------------------------ synthetic tests --------------------------- #
def test_find_dicom_root_skips_viewer(tmp_path):
    _make_weasis_like(tmp_path / "STUDY")
    root = find_dicom_root(tmp_path)
    assert root is not None
    assert root.name.lower() == "dicom"
    assert "weasis" not in str(root).lower()
    assert "__macosx" not in str(root).lower()


def test_enumerate_series_and_laterality(tmp_path):
    uid = _make_weasis_like(tmp_path / "STUDY", laterality="right", n=4)
    root = find_dicom_root(tmp_path)
    series = enumerate_series(root)
    assert len(series) == 1
    s = series[0]
    assert s.series_uid == uid
    assert s.n_instances == 4
    assert s.modality == "CT"
    assert s.laterality == "right"
    assert s.pixel_spacing == (0.5, 0.5)


def test_compute_isotropy():
    assert compute_isotropy((1.0, 1.0), 1.0) is True
    assert compute_isotropy((0.5, 0.5), 1.0) is False   # 2x anisotropic
    assert compute_isotropy(None, 1.0) is False


def test_ingest_report_is_deidentified(tmp_path):
    _make_weasis_like(tmp_path / "STUDY", n=3)
    rep = ingest_source(tmp_path, tmp_path / "_wd", load_pixels=False)
    pub = rep.public_dict()
    blob = str(pub)
    for phi in ("PHANTOM", "PatientID", "PatientName", "file_paths"):
        assert phi not in blob
    assert pub["patient_hash"] and len(pub["patient_hash"]) == 8
    assert pub["n_series"] == 1


def test_select_bone_series_prefers_axial_bone_kernel():
    """Mirrors the real archive's series mix; bone-kernel axial must win over
    the larger sagittal reformat, scout, and dose report."""
    series = [
        SeriesInfo(series_uid="a", modality="CT", description="SAGITAL",
                   n_instances=493, slice_thickness=0.977),
        SeriesInfo(series_uid="b", modality="CT", description="CORONAL",
                   n_instances=275, slice_thickness=0.977),
        SeriesInfo(series_uid="c", modality="CT", description="L+R OMUZ 1.25mm  Bone",
                   n_instances=195, slice_thickness=1.25),
        SeriesInfo(series_uid="d", modality="CT", description="L+R OMUZ 1.25mm",
                   n_instances=195, slice_thickness=1.25),
        SeriesInfo(series_uid="e", modality="CT", description="Scout",
                   n_instances=1, slice_thickness=260.0),
        SeriesInfo(series_uid="f", modality="CT", description="Dose Report",
                   n_instances=1),
    ]
    best = select_bone_series(series)
    assert best.description == "L+R OMUZ 1.25mm  Bone"


# ------------------------------ real-data tests --------------------------- #
@pytest.mark.realdata
@pytest.mark.skipif(len(ZIPS) < 1, reason="patient CT zips not present")
def test_real_ingest_finds_dicom(tmp_path):
    rep = ingest_source(ZIPS[0], tmp_path, load_pixels=False)
    assert rep.dicom_root is not None
    assert rep.n_dicom_files > 0
    assert rep.primary_series() is not None
    assert rep.primary_series().modality.upper() == "CT"


@pytest.mark.realdata
@pytest.mark.skipif(len(ZIPS) < 2, reason="need both patient CT zips")
def test_real_compare_scans(tmp_path):
    a = ingest_source(ZIPS[0], tmp_path / "a", load_pixels=False)
    b = ingest_source(ZIPS[1], tmp_path / "b", load_pixels=False)
    res = compare_scans(a, b)
    assert isinstance(res.distinct, bool)
    assert res.reason
