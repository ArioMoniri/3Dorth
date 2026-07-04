"""MPR slice module: plane extraction, windowing, aspect, world<->voxel, PNG."""
import io

import numpy as np
import pytest

from core.viz import slice as S


def _vol():
    # arr[z,y,x] = z*100 + y*10 + x, shape (4, 6, 8)
    z, y, x = np.mgrid[0:4, 0:6, 0:8]
    return (z * 100 + y * 10 + x).astype(np.int16)


def test_extract_slice_planes():
    a = _vol()
    ax = S.extract_slice(a, "axial", 2)      # arr[2] -> (y, x)
    assert ax.shape == (6, 8) and ax[3, 5] == 200 + 35
    co = S.extract_slice(a, "coronal", 3)    # arr[:,3,:] -> (z, x)
    assert co.shape == (4, 8) and co[2, 5] == 200 + 30 + 5
    sa = S.extract_slice(a, "sagittal", 5)   # arr[:,:,5] -> (z, y)
    assert sa.shape == (4, 6) and sa[2, 4] == 200 + 40 + 5


def test_clamp_index():
    a = _vol()
    assert S.clamp_index(a.shape, "axial", 99) == 3   # nz-1
    assert S.clamp_index(a.shape, "axial", -5) == 0
    assert S.extract_slice(a, "axial", 99).shape == (6, 8)  # holds last


def test_window_to_uint8():
    sl = np.array([[-1000, 400, 1300]], dtype=np.int16)  # level 400, window 1800
    out = S.window_to_uint8(sl, window=1800, level=400)
    assert out[0, 0] == 0        # at/below lo (400-900=-500) -> -1000 clips to 0
    assert 126 <= out[0, 1] <= 129   # at level -> ~mid
    assert out[0, 2] == 255      # at/above hi (400+900=1300) -> 255


def test_aspect_resample_makes_square_mm_and_caps():
    img = np.zeros((4, 8), dtype=np.uint8)   # rows*2mm=8, cols*1mm=8 -> square
    out = S.aspect_resample(img, row_sp=2.0, col_sp=1.0, max_dim=512)
    assert out.shape == (8, 8)               # native px=1mm -> 8x8
    big = np.zeros((10, 10), dtype=np.uint8)
    capped = S.aspect_resample(big, 1.0, 1.0, max_dim=5)
    assert max(capped.shape) <= 5


def test_world_voxel_roundtrip():
    spacing = (0.5, 0.5, 1.25)
    offset = (10.0, 0.0, 0.0)
    ijk = (3, 5, 2)
    w = S.voxel_to_world(ijk, spacing, offset)
    assert w == (11.5, 2.5, 2.5)
    assert S.world_to_voxel(w, spacing, offset) == ijk


def test_slices_from_voxel():
    a = _vol()
    out = S.slices_from_voxel((5, 3, 2), a.shape)  # ix=5,iy=3,iz=2
    assert out == {"axial": 2, "coronal": 3, "sagittal": 5}


def test_render_slice_png_is_valid_image():
    from PIL import Image

    a = _vol()
    png = S.render_slice_png(a, (0.977, 0.977, 1.25), "axial", 2, max_dim=64)
    im = Image.open(io.BytesIO(png))
    assert im.format == "PNG" and im.mode == "L"
    assert max(im.size) <= 64


def test_render_slice_png_overlay_is_rgb():
    a = _vol()
    mask = a >= 300
    png = S.render_slice_png(a, (1, 1, 1), "axial", 3, overlay_mask=mask, max_dim=32)
    from PIL import Image
    assert Image.open(io.BytesIO(png)).mode == "RGB"


def test_volume_info_fields():
    a = _vol()
    vi = S.volume_info(a, (0.5, 0.5, 1.25), (10.0, 0.0, 0.0), "left")
    assert vi["shape_zyx"] == [4, 6, 8]
    assert vi["n_slices"] == {"axial": 4, "coronal": 6, "sagittal": 8}
    assert vi["orientation"] == "array"       # never claims radiological
    assert vi["offset_xyz_mm"][0] == 10.0


def test_unknown_plane_raises():
    with pytest.raises(ValueError):
        S.extract_slice(_vol(), "oblique", 0)
