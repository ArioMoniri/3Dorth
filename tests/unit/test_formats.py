"""New input formats + single-side/bilateral detection.

Round-trips a NIfTI volume and surface meshes with KNOWN geometry so every
assertion is verifiable, and drives the bilateral detector with synthetic
single-sided and two-sided volumes whose answer is known by construction.
"""
import numpy as np
import pytest
import pyvista as pv
import SimpleITK as sitk

from core import pipeline
from core.ingest import (
    MESH_EXTENSIONS,
    NIFTI_EXTENSIONS,
    is_mesh,
    is_nifti,
    load_mesh_source,
    load_nifti_volume,
)


# ------------------------------- NIfTI ------------------------------------ #
def _write_nifti(path, arr_zyx, spacing_xyz):
    img = sitk.GetImageFromArray(np.ascontiguousarray(arr_zyx.astype(np.float32)))
    img.SetSpacing(tuple(float(s) for s in spacing_xyz))
    sitk.WriteImage(img, str(path))


@pytest.mark.parametrize("suffix", [".nii", ".nii.gz"])
def test_load_nifti_volume_roundtrip(tmp_path, suffix):
    arr = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)  # (z, y, x)
    spacing = (1.5, 2.0, 3.0)  # (sx, sy, sz)
    p = tmp_path / f"vol{suffix}"
    _write_nifti(p, arr, spacing)

    out_arr, out_spacing, meta = load_nifti_volume(p)
    assert out_arr.dtype == np.float32
    assert out_arr.shape == (2, 3, 4)
    assert np.allclose(out_arr, arr)
    assert np.allclose(out_spacing, spacing)
    assert meta["format"] == "nifti"
    assert meta["shape"] == [2, 3, 4]


@pytest.mark.parametrize("suffix", [".nii", ".nii.gz"])
def test_pipeline_load_volume_handles_nifti(tmp_path, suffix):
    arr = np.full((6, 8, 10), -800.0, dtype=np.float32)
    arr[2:4, 3:5, 4:6] = 700.0
    spacing = (0.5, 0.5, 1.0)
    p = tmp_path / f"scan{suffix}"
    _write_nifti(p, arr, spacing)

    out_arr, out_spacing, meta = pipeline.load_volume_from_source(p, tmp_path / "_wd")
    assert out_arr.shape == arr.shape
    assert np.allclose(out_arr, arr)
    assert np.allclose(out_spacing, spacing)
    assert meta["format"] == "nifti"
    # keeps the keys DICOM path callers already read
    for k in ("series", "laterality", "patient_hash"):
        assert k in meta


def test_is_nifti_helper():
    assert is_nifti("a.nii")
    assert is_nifti("a.NII.GZ")
    assert not is_nifti("a.zip")
    assert set(NIFTI_EXTENSIONS) == {".nii", ".nii.gz"}


# -------------------------------- meshes ---------------------------------- #
@pytest.mark.parametrize("fmt", ["stl", "ply", "obj", "vtp"])
def test_load_mesh_source_roundtrip(tmp_path, fmt):
    sphere = pv.Sphere()
    n = sphere.n_points
    p = tmp_path / f"m.{fmt}"
    sphere.save(str(p))

    mesh = load_mesh_source(p)
    assert isinstance(mesh, pv.PolyData)
    assert mesh.n_points > 0
    # STL re-tessellates but keeps a comparable vertex count; others match exactly
    if fmt in ("ply", "vtp", "obj"):
        assert mesh.n_points == n
    assert "Normals" in mesh.point_data


def test_load_mesh_via_pipeline(tmp_path):
    sphere = pv.Sphere()
    p = tmp_path / "m.vtp"
    sphere.save(str(p))
    mesh = pipeline.load_mesh_source(p)
    assert isinstance(mesh, pv.PolyData)
    assert mesh.n_points == sphere.n_points


def test_is_mesh_helper():
    assert is_mesh("a.STL") and is_mesh("b.ply") and is_mesh("c.obj") and is_mesh("d.vtp")
    assert not is_mesh("a.nii")
    assert set(MESH_EXTENSIONS) == {".stl", ".ply", ".obj", ".vtp"}


def test_load_mesh_rejects_unsupported(tmp_path):
    p = tmp_path / "x.foo"
    p.write_text("nope")
    with pytest.raises(ValueError):
        load_mesh_source(p)


# ------------------------ supported extensions ---------------------------- #
def test_supported_upload_extensions():
    assert pipeline.SUPPORTED_UPLOAD_EXTENSIONS == (
        ".zip", ".nii", ".nii.gz", ".stl", ".ply", ".obj", ".vtp"
    )


# ----------------------- single-side vs bilateral ------------------------- #
def _single_sided_volume():
    arr = np.full((30, 40, 60), -1000.0, dtype=np.float32)
    arr[8:22, 12:28, 8:20] = 800.0  # one mass, low-x half only
    return arr


def _bilateral_volume():
    arr = np.full((30, 40, 60), -1000.0, dtype=np.float32)
    arr[8:22, 12:28, 6:20] = 800.0    # right mass
    arr[8:22, 12:28, 40:54] = 800.0   # left mass, separated by a central gap
    return arr


def test_detect_bilateral_true_and_false():
    assert pipeline.detect_bilateral(_bilateral_volume(), (1.0, 1.0, 1.0)) is True
    assert pipeline.detect_bilateral(_single_sided_volume(), (1.0, 1.0, 1.0)) is False


def test_detect_bilateral_empty_is_false():
    arr = np.full((10, 10, 10), -1000.0, dtype=np.float32)
    assert pipeline.detect_bilateral(arr, (1.0, 1.0, 1.0)) is False


def test_split_sides_single_returns_full():
    sides = pipeline.split_sides(_single_sided_volume(), (1.0, 1.0, 1.0))
    assert list(sides.keys()) == ["full"]
    full = sides["full"]
    assert full["side"] == "full"
    assert full["offset_xyz"] == (0.0, 0.0, 0.0)
    assert full["arr"].shape == _single_sided_volume().shape
    # spacing carried
    assert full["spacing"] == (1.0, 1.0, 1.0)


def test_split_sides_bilateral_returns_left_right():
    arr = _bilateral_volume()
    sides = pipeline.split_sides(arr, (1.0, 1.0, 1.0))
    assert set(sides.keys()) == {"left", "right"}
    for name in ("left", "right"):
        s = sides[name]
        assert s["side"] == name
        assert "arr" in s and "spacing" in s and "offset_xyz" in s
    # right keeps the origin; left is offset in +x (shared coordinate frame)
    assert sides["right"]["offset_xyz"] == (0.0, 0.0, 0.0)
    assert sides["left"]["offset_xyz"][0] > 0.0


def test_split_sides_keys_indexable_by_side_name():
    """Callers iterate .keys() and index by side name; both shapes must support it."""
    for arr in (_single_sided_volume(), _bilateral_volume()):
        sides = pipeline.split_sides(arr, (1.0, 1.0, 1.0))
        for key in sides.keys():
            entry = sides[key]
            assert entry["side"] == key
            assert set(("arr", "spacing", "offset_xyz")) <= set(entry)
