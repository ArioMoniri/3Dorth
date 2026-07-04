"""DICOM/zip ingest with de-identification.

Handles the sample archives, which wrap a Weasis viewer around the real images
in a ``dicom/`` subfolder. Recurses past the viewer and ``__MACOSX`` junk,
groups files by DICOM series, and reports geometry, laterality, hardware
presence, and a distinct-scan comparison — all de-identified (no name / MRN /
dates leave this module).
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import numpy as np
import pydicom
import SimpleITK as sitk
from pydicom.errors import InvalidDicomError
from pydantic import BaseModel

# HU above this is treated as metal / hardware (default; the registry mirrors it).
DEFAULT_METAL_HU = 2000


# --------------------------------------------------------------------------- #
# Data models (de-identified — no PatientName / MRN / dates)
# --------------------------------------------------------------------------- #
class SeriesInfo(BaseModel):
    series_uid: str
    modality: str = ""
    description: str = ""
    n_instances: int = 0
    rows: int | None = None
    cols: int | None = None
    pixel_spacing: tuple[float, float] | None = None  # (row, col) mm
    slice_thickness: float | None = None
    spacing_between_slices: float | None = None
    laterality: str = "unknown"
    body_part: str = ""
    is_isotropic: bool = False
    # internal (not persisted to user-facing outputs)
    file_paths: list[str] = []

    def public_dict(self) -> dict:
        d = self.model_dump()
        d.pop("file_paths", None)
        return d


class IngestReport(BaseModel):
    source_name: str            # zip/dir basename (may be patient-named -> hashed for outputs)
    patient_hash: str           # sha8 of PatientID (cross-reference without PHI)
    source_hash: str            # sha8 of source_name
    dicom_root: str | None
    n_dicom_files: int
    series: list[SeriesInfo]
    laterality: str = "unknown"
    metal_present: bool = False
    metal_fraction: float = 0.0
    hu_min: float | None = None
    hu_max: float | None = None

    def public_dict(self) -> dict:
        """De-identified dict safe to print / write to outputs/."""
        return {
            "source_hash": self.source_hash,
            "patient_hash": self.patient_hash,
            "dicom_root_found": self.dicom_root is not None,
            "n_dicom_files": self.n_dicom_files,
            "n_series": len(self.series),
            "laterality": self.laterality,
            "metal_present": self.metal_present,
            "metal_fraction": round(self.metal_fraction, 6),
            "hu_min": self.hu_min,
            "hu_max": self.hu_max,
            "series": [s.public_dict() for s in self.series],
        }

    def primary_series(self) -> SeriesInfo | None:
        """The most likely main CT series: CT modality, most instances."""
        cands = [s for s in self.series if s.modality.upper() == "CT"] or self.series
        return max(cands, key=lambda s: s.n_instances, default=None)


class DistinctScanResult(BaseModel):
    distinct: bool
    reason: str
    same_patient: bool
    a_primary: dict | None = None
    b_primary: dict | None = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _sha8(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:8]


def find_dicom_root(root: Path) -> Path | None:
    """Return the directory holding the DICOM images.

    Prefers a directory literally named ``dicom`` (case-insensitive) that is not
    inside a Weasis/viewer or ``__MACOSX`` tree; falls back to the deepest
    directory containing the most DICOM-looking files.
    """
    root = Path(root)
    skip = ("__macosx", "weasis", "bundle", "viewer")
    dicom_dirs: list[Path] = []
    for d in root.rglob("*"):
        if not d.is_dir():
            continue
        parts = [p.lower() for p in d.parts]
        if any(s in part for part in parts for s in skip):
            continue
        if d.name.lower() == "dicom":
            dicom_dirs.append(d)
    if dicom_dirs:
        return max(dicom_dirs, key=lambda p: sum(1 for _ in p.rglob("*") if _.is_file()))
    return None


def _read_header(path: Path):
    try:
        return pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    except (InvalidDicomError, Exception):  # noqa: BLE001
        return None


def _laterality_from_ds(ds) -> str:
    for tag in ("ImageLaterality", "Laterality"):
        v = getattr(ds, tag, None)
        if v in ("R", "L"):
            return "right" if v == "R" else "left"
    text = " ".join(
        str(getattr(ds, t, "")) for t in ("SeriesDescription", "StudyDescription", "BodyPartExamined")
    ).lower()
    if "bilat" in text or ("right" in text and "left" in text):
        return "bilateral"
    if "right" in text or " rt" in text or text.endswith(" r"):
        return "right"
    if "left" in text or " lt" in text or text.endswith(" l"):
        return "left"
    return "unknown"


def compute_isotropy(pixel_spacing, slice_thickness, tol: float = 0.15) -> bool:
    """True if in-plane and through-plane spacings are within ``tol`` relative."""
    if not pixel_spacing or slice_thickness in (None, 0):
        return False
    sr, sc = float(pixel_spacing[0]), float(pixel_spacing[1])
    st = float(slice_thickness)
    vals = [sr, sc, st]
    return (max(vals) - min(vals)) / max(vals) <= tol


def enumerate_series(dicom_dir: Path) -> list[SeriesInfo]:
    """Group DICOM files under ``dicom_dir`` by SeriesInstanceUID."""
    groups: dict[str, list[tuple[Path, object]]] = {}
    for f in Path(dicom_dir).rglob("*"):
        if not f.is_file():
            continue
        ds = _read_header(f)
        if ds is None:
            continue
        uid = getattr(ds, "SeriesInstanceUID", None)
        if not uid or hasattr(ds, "DirectoryRecordSequence"):  # skip DICOMDIR
            continue
        groups.setdefault(str(uid), []).append((f, ds))

    infos: list[SeriesInfo] = []
    for uid, items in groups.items():
        ds0 = items[0][1]
        ps = getattr(ds0, "PixelSpacing", None)
        pixel_spacing = (float(ps[0]), float(ps[1])) if ps else None
        st = getattr(ds0, "SliceThickness", None)
        st = float(st) if st not in (None, "") else None
        sbs = getattr(ds0, "SpacingBetweenSlices", None)
        sbs = float(sbs) if sbs not in (None, "") else None

        def _sort_key(item):
            _, ds = item
            ipp = getattr(ds, "ImagePositionPatient", None)
            if ipp is not None and len(ipp) == 3:
                return float(ipp[2])
            return float(getattr(ds, "InstanceNumber", 0) or 0)

        items_sorted = sorted(items, key=_sort_key)
        infos.append(
            SeriesInfo(
                series_uid=uid,
                modality=str(getattr(ds0, "Modality", "")),
                description=str(getattr(ds0, "SeriesDescription", "")),
                n_instances=len(items),
                rows=int(getattr(ds0, "Rows", 0)) or None,
                cols=int(getattr(ds0, "Columns", 0)) or None,
                pixel_spacing=pixel_spacing,
                slice_thickness=st,
                spacing_between_slices=sbs,
                laterality=_laterality_from_ds(ds0),
                body_part=str(getattr(ds0, "BodyPartExamined", "")),
                is_isotropic=compute_isotropy(pixel_spacing, st),
                file_paths=[str(p) for p, _ in items_sorted],
            )
        )
    infos.sort(key=lambda s: s.n_instances, reverse=True)
    return infos


def _extract_dicom(zip_path: Path, workdir: Path) -> Path:
    """Extract only the ``dicom/`` members of a zip into a de-identified dir."""
    zip_path = Path(zip_path)
    dest = Path(workdir) / f"scan_{_sha8(zip_path.name)}"
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = [
            m for m in zf.namelist()
            if "/dicom/" in m.lower() and "__macosx" not in m.lower() and not m.endswith("/")
        ]
        for m in members:
            target = dest / m
            if not str(target.resolve()).startswith(str(dest.resolve())):
                continue  # path-traversal guard
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                with zf.open(m) as src, open(target, "wb") as out:
                    out.write(src.read())
    return dest


def load_series_volume(series: SeriesInfo) -> sitk.Image:
    """Load a series' voxels as a SimpleITK image in HU (rescale applied)."""
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(series.file_paths)
    img = reader.Execute()
    arr = sitk.GetArrayFromImage(img)
    # Defensive rescale: if the reader returned raw stored values (no negatives)
    # but the header carries a negative intercept, apply the modality LUT.
    if arr.min() >= 0 and series.file_paths:
        ds = _read_header(Path(series.file_paths[0]))
        intercept = float(getattr(ds, "RescaleIntercept", 0) or 0)
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        if intercept < 0 or slope != 1:
            out = sitk.Cast(img, sitk.sitkFloat32) * slope + intercept
            out.CopyInformation(img)
            return out
    return img


def _patient_hash(dicom_dir: Path) -> str:
    for f in Path(dicom_dir).rglob("*"):
        if f.is_file():
            ds = _read_header(f)
            if ds is not None:
                pid = str(getattr(ds, "PatientID", "") or getattr(ds, "PatientName", ""))
                return _sha8(pid) if pid else "unknown0"
    return "unknown0"


def ingest_source(
    path: Path, workdir: Path, metal_hu: int = DEFAULT_METAL_HU, load_pixels: bool = True
) -> IngestReport:
    """Ingest a ``.zip`` or a DICOM directory into a de-identified report."""
    path = Path(path)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    if path.suffix.lower() == ".zip":
        extracted = _extract_dicom(path, workdir)
        dicom_root = find_dicom_root(extracted)
    elif path.is_dir():
        dicom_root = find_dicom_root(path) or path
    else:
        raise ValueError(f"Unsupported ingest source: {path}")

    series = enumerate_series(dicom_root) if dicom_root else []
    n_files = sum(len(s.file_paths) for s in series)
    patient_hash = _patient_hash(dicom_root) if dicom_root else "unknown0"

    report = IngestReport(
        source_name=path.name,
        patient_hash=patient_hash,
        source_hash=_sha8(path.name),
        dicom_root=str(dicom_root) if dicom_root else None,
        n_dicom_files=n_files,
        series=series,
        laterality=_combine_laterality(series),
    )

    primary = report.primary_series()
    if load_pixels and primary is not None and primary.n_instances >= 2:
        try:
            img = load_series_volume(primary)
            arr = sitk.GetArrayViewFromImage(img)
            report.hu_min = float(np.min(arr))
            report.hu_max = float(np.max(arr))
            metal = int(np.count_nonzero(arr > metal_hu))
            report.metal_fraction = metal / arr.size
            report.metal_present = report.metal_fraction > 1e-5
        except Exception:  # noqa: BLE001 — report stays honest about what loaded
            pass
    return report


def _combine_laterality(series: list[SeriesInfo]) -> str:
    lats = {s.laterality for s in series if s.laterality != "unknown"}
    if not lats:
        return "unknown"
    if lats == {"left"} or lats == {"right"}:
        return lats.pop()
    if "bilateral" in lats or lats >= {"left", "right"}:
        return "bilateral"
    return "/".join(sorted(lats))


def compare_scans(a: IngestReport, b: IngestReport) -> DistinctScanResult:
    """Decide whether two ingested sources are genuinely different scans."""
    same_patient = a.patient_hash == b.patient_hash and a.patient_hash != "unknown0"
    pa, pb = a.primary_series(), b.primary_series()
    if pa is None or pb is None:
        return DistinctScanResult(
            distinct=False, reason="one source has no loadable series",
            same_patient=same_patient,
        )
    sig_a = (pa.n_instances, pa.rows, pa.cols, pa.series_uid)
    sig_b = (pb.n_instances, pb.rows, pb.cols, pb.series_uid)
    if pa.series_uid == pb.series_uid and pa.n_instances == pb.n_instances:
        reason = "identical primary SeriesInstanceUID and instance count (likely duplicate copy)"
        distinct = False
    elif (pa.n_instances, pa.rows, pa.cols) != (pb.n_instances, pb.rows, pb.cols):
        reason = f"primary series differ in size {sig_a[:3]} vs {sig_b[:3]}"
        distinct = True
    else:
        reason = "different SeriesInstanceUID, same geometry — distinct reconstruction/series"
        distinct = True
    return DistinctScanResult(
        distinct=distinct, reason=reason, same_patient=same_patient,
        a_primary=pa.public_dict(), b_primary=pb.public_dict(),
    )
