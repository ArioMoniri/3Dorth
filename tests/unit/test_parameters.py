"""Registry is the single source of truth — lock its invariants."""
import pytest

import core.parameters as P


def test_registry_nonempty_and_unique():
    assert len(P.REGISTRY) > 0
    assert P._duplicate_keys() == []
    assert len(P.registry_keys()) == len(set(P.registry_keys()))


def test_article_defaults():
    p = P.default_parameters()
    assert p.hu_lower == 226
    assert p.hu_upper == 1600
    assert p.metal_hu_cutoff == 2000
    assert p.thickness_min_clamp == 0.33
    assert p.thickness_max_clamp == 10.0
    assert p.thickness_algorithm == "local_thickness"
    assert p.mode_a_colormap == "green_yellow_red"
    assert p.mode_a_colorbar_steps == 7
    assert p.mode_a_range_min == pytest.approx(0.1537)
    assert p.mode_a_range_max == pytest.approx(6.5202)
    assert p.measure_line_points == 3


def test_generated_model_matches_registry():
    """The Parameters model is generated from the registry -> keys must match."""
    fields = set(P.Parameters().model_dump().keys())
    assert fields == set(P.registry_keys())


def test_range_validation_rejects_out_of_bounds():
    with pytest.raises(Exception):
        P.Parameters(hu_lower=99999)
    with pytest.raises(Exception):
        P.Parameters(thickness_min_clamp=-1.0)


def test_enum_validation():
    with pytest.raises(Exception):
        P.Parameters(mode_a_colormap="not_a_real_map")


def test_config_roundtrip(tmp_path):
    cfg = tmp_path / "config.yaml"
    P.save_parameters(P.default_parameters(), cfg, extra={"meta": {"x": 1}})
    loaded = P.load_parameters(cfg)
    assert loaded.model_dump() == P.default_parameters().model_dump()


def test_mode_partitioning():
    a_keys = {s.key for s in P.registry_for_mode("A")}
    b_keys = {s.key for s in P.registry_for_mode("B")}
    # Shared params appear in both; mode-specific ones do not cross over.
    assert "thickness_algorithm" in a_keys and "thickness_algorithm" not in b_keys
    assert "reg_icp_iters" in b_keys and "reg_icp_iters" not in a_keys
    assert "hu_lower" in a_keys and "hu_lower" in b_keys  # 'both'


def test_control_dicts_shape():
    dicts = P.control_dicts()
    assert len(dicts) == len(P.REGISTRY)
    for d in dicts:
        assert {"key", "label", "group", "control", "default"} <= set(d)
