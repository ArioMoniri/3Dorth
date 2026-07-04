"""Export module: multi-format figure/mesh/DICOM-SC/bundle output.

Uses a small synthetic mesh with a KNOWN scalar so every assertion checks a real,
verifiable property (file non-trivial, TIFF DPI read back, PLY point count, DICOM
readable + no PHI).
"""
import numpy as np
import pydicom
import pytest
import pyvista as pv
from PIL import Image

import core.parameters as P
from core.export import (
    export_bundle,
    export_dicom_secondary_capture,
    export_figure,
    export_mesh,
)
from core.meshing import mask_to_mesh


def _thickness_mesh():
    mask = np.zeros((20, 20, 20), dtype=bool)
    mask[5:15, 5:15, 5:15] = True
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    mesh["thickness_mm"] = np.linspace(0.5, 5.0, mesh.n_points)
    return mesh


def _deviation_mesh():
    mask = np.zeros((20, 20, 20), dtype=bool)
    mask[5:15, 5:15, 5:15] = True
    mesh = mask_to_mesh(mask, (1.0, 1.0, 1.0), smooth_iters=0)
    mesh["deviation_mm"] = np.linspace(-3.0, 3.0, mesh.n_points)
    return mesh


# ------------------------------- figures ---------------------------------- #
@pytest.mark.parametrize("fmt", ["png", "tiff", "jpg"])
def test_export_figure_formats_write_nontrivial(tmp_path, fmt):
    mesh = _thickness_mesh()
    out = export_figure(mesh, "thickness_mm", P.default_parameters(),
                        tmp_path / f"fig.{fmt}", fmt=fmt, dpi=150)
    assert out.exists()
    assert out.stat().st_size > 5000
    im = Image.open(out)
    assert im.width > 100 and im.height > 100


def test_export_tiff_embeds_requested_dpi(tmp_path):
    mesh = _thickness_mesh()
    for dpi in (150, 300):
        out = export_figure(mesh, "thickness_mm", P.default_parameters(),
                            tmp_path / f"fig_{dpi}.tiff", fmt="tiff", dpi=dpi)
        im = Image.open(out)
        assert im.format == "TIFF"
        got = im.info.get("dpi")
        assert got is not None
        assert abs(float(got[0]) - dpi) < 1.0
        assert abs(float(got[1]) - dpi) < 1.0


def test_export_jpg_embeds_dpi(tmp_path):
    mesh = _thickness_mesh()
    out = export_figure(mesh, "thickness_mm", P.default_parameters(),
                        tmp_path / "fig.jpg", fmt="jpg", dpi=200)
    im = Image.open(out)
    got = im.info.get("dpi")
    assert got is not None and abs(float(got[0]) - 200) < 1.0


def test_export_figure_camera_pose_adjuster(tmp_path):
    """The pose adjuster must run without error and still produce a valid image."""
    mesh = _thickness_mesh()
    out = export_figure(mesh, "thickness_mm", P.default_parameters(),
                        tmp_path / "posed.png", fmt="png", dpi=120,
                        camera={"azimuth": 30, "elevation": 15, "roll": 5, "zoom": 1.2})
    assert out.exists() and out.stat().st_size > 5000


def test_export_figure_diverging_uses_mode_b(tmp_path):
    mesh = _deviation_mesh()
    out = export_figure(mesh, "deviation_mm", P.default_parameters(),
                        tmp_path / "dev.png", fmt="png", dpi=120, diverging=True,
                        label="Signed deviation (mm)")
    assert out.exists() and out.stat().st_size > 5000


def test_export_figure_rejects_bad_format(tmp_path):
    mesh = _thickness_mesh()
    with pytest.raises(ValueError):
        export_figure(mesh, "thickness_mm", P.default_parameters(),
                      tmp_path / "x.gif", fmt="gif")


# -------------------------------- meshes ---------------------------------- #
@pytest.mark.parametrize("fmt", ["stl", "ply", "obj", "vtp"])
def test_export_mesh_formats_write_nontrivial(tmp_path, fmt):
    mesh = _thickness_mesh()
    out = export_mesh(mesh, tmp_path / f"m.{fmt}", fmt=fmt, scalar_name="thickness_mm")
    assert out.exists() and out.stat().st_size > 200


def test_export_mesh_ply_preserves_point_count(tmp_path):
    mesh = _thickness_mesh()
    n = mesh.n_points
    out = export_mesh(mesh, tmp_path / "m.ply", fmt="ply", scalar_name="thickness_mm")
    back = pv.read(str(out))
    assert back.n_points == n


def test_export_mesh_vtp_carries_scalar(tmp_path):
    mesh = _thickness_mesh()
    out = export_mesh(mesh, tmp_path / "m.vtp", fmt="vtp", scalar_name="thickness_mm")
    back = pv.read(str(out))
    assert "thickness_mm" in back.point_data
    assert back.n_points == mesh.n_points


def test_export_mesh_rejects_bad_format(tmp_path):
    mesh = _thickness_mesh()
    with pytest.raises(ValueError):
        export_mesh(mesh, tmp_path / "m.xyz", fmt="xyz")


# ------------------------------- DICOM SC --------------------------------- #
def test_export_dicom_secondary_capture_readable_and_no_phi(tmp_path):
    rgb = (np.random.default_rng(0).uniform(0, 255, (64, 80, 3))).astype(np.uint8)
    out = export_dicom_secondary_capture(rgb, tmp_path / "sc.dcm",
                                         description="3Dorth export")
    assert out.exists()
    ds = pydicom.dcmread(str(out))
    # readable pixels, correct geometry
    assert ds.Rows == 64 and ds.Columns == 80 and ds.SamplesPerPixel == 3
    assert ds.pixel_array.shape == (64, 80, 3)
    assert np.array_equal(ds.pixel_array, rgb)
    # no PHI
    for tag in ("PatientBirthDate", "StudyDate", "SeriesDate", "AcquisitionDate",
                "InstitutionName", "ReferringPhysicianName", "AccessionNumber"):
        assert not getattr(ds, tag, "")
    assert str(getattr(ds, "PatientName", "")) == ""
    assert str(getattr(ds, "PatientID", "")) == ""
    assert ds.PatientIdentityRemoved == "YES"
    assert ds.ImageComments == "3Dorth export"


def test_export_dicom_rejects_non_rgb(tmp_path):
    with pytest.raises(ValueError):
        export_dicom_secondary_capture(np.zeros((10, 10), dtype=np.uint8),
                                       tmp_path / "bad.dcm")


# -------------------------------- bundle ---------------------------------- #
def test_export_bundle_writes_all_requested(tmp_path):
    mesh = _thickness_mesh()
    files = export_bundle(mesh, "thickness_mm", P.default_parameters(), tmp_path,
                          formats=("png", "tiff", "stl", "vtp"), dpi=120)
    assert set(files.keys()) == {"png", "tiff", "stl", "vtp"}
    from pathlib import Path
    for _fmt, p in files.items():
        assert Path(p).exists() and Path(p).stat().st_size > 200
    # TIFF dpi preserved through the bundle path too
    tif = Image.open(files["tiff"])
    assert abs(float(tif.info["dpi"][0]) - 120) < 1.0


def test_export_bundle_includes_dicom(tmp_path):
    mesh = _deviation_mesh()
    files = export_bundle(mesh, "deviation_mm", P.default_parameters(), tmp_path,
                          formats=("png", "dicom", "vtp"), dpi=120, diverging=True)
    assert set(files.keys()) == {"png", "dicom", "vtp"}
    ds = pydicom.dcmread(files["dicom"])
    assert ds.SamplesPerPixel == 3
    assert str(getattr(ds, "PatientID", "")) == ""
