"""Manual-registration adjust: transform composition + backward-compatible signature.

The heavy Mode-B compute (segmentation + ICP on real data) is not exercised here;
instead the composition math is checked against a KNOWN answer, and the public
signature is asserted to stay backward compatible (manual_transform defaults None).
"""
import inspect

import numpy as np

from core import pipeline
from core.pipeline import _compose_transforms


def _translation(tx, ty, tz):
    T = np.eye(4)
    T[:3, 3] = [tx, ty, tz]
    return T


def test_compose_none_is_auto_identity():
    auto = _translation(1.0, 2.0, 3.0)
    out = _compose_transforms(auto.tolist(), None)
    assert np.allclose(out, auto)


def test_compose_applies_manual_after_auto():
    """manual @ auto: a point is first moved by auto, then by manual."""
    auto = _translation(1.0, 0.0, 0.0)      # +1 in x
    manual = _translation(0.0, 5.0, 0.0)    # +5 in y, applied AFTER
    composed = _compose_transforms(auto.tolist(), manual.tolist())
    p = np.array([0.0, 0.0, 0.0, 1.0])
    moved = composed @ p
    assert np.allclose(moved[:3], [1.0, 5.0, 0.0])


def test_compose_manual_rotation_after_translation():
    auto = _translation(2.0, 0.0, 0.0)
    # manual = 90deg about z
    c, s = np.cos(np.pi / 2), np.sin(np.pi / 2)
    manual = np.eye(4)
    manual[:3, :3] = [[c, -s, 0], [s, c, 0], [0, 0, 1]]
    composed = _compose_transforms(auto.tolist(), manual.tolist())
    # a point at origin -> auto sends to (2,0,0) -> manual rotates to (0,2,0)
    moved = composed @ np.array([0.0, 0.0, 0.0, 1.0])
    assert np.allclose(moved[:3], [0.0, 2.0, 0.0], atol=1e-9)


def test_compose_rejects_bad_manual_shape():
    auto = np.eye(4)
    import pytest
    with pytest.raises(ValueError):
        _compose_transforms(auto.tolist(), [[1, 0], [0, 1]])


def test_compare_sides_signature_backward_compatible():
    sig = inspect.signature(pipeline.compare_sides)
    params = sig.parameters
    # original positional params unchanged
    assert list(params)[:3] == ["ref", "tgt", "params"]
    # manual_transform is a new OPTIONAL keyword-only param defaulting to None
    assert "manual_transform" in params
    mt = params["manual_transform"]
    assert mt.default is None
    assert mt.kind == inspect.Parameter.KEYWORD_ONLY
