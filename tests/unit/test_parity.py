"""Feature parity: both frontends expose exactly the registry parameter set.

Parity is structural — the trame UI reads ``app_trame.controls.control_specs``
and the React UI reads the API's ``/api/parameters`` — and both must equal
``core.parameters.registry_keys()``.
"""
from fastapi.testclient import TestClient

import core.parameters as P
from api.main import app
from app_trame.controls import control_keys, control_specs

CLIENT = TestClient(app)


def test_api_parameters_match_registry():
    r = CLIENT.get("/api/parameters")
    assert r.status_code == 200
    data = r.json()
    assert data["keys"] == P.registry_keys()
    assert [c["key"] for c in data["controls"]] == P.registry_keys()
    assert set(data["defaults"].keys()) == set(P.registry_keys())


def test_trame_controls_match_registry():
    assert control_keys() == P.registry_keys()
    for c in control_specs():
        assert {"key", "label", "group", "control", "default"} <= set(c)


def test_both_uis_expose_identical_control_set():
    """The React source (API) and the trame source must be identical."""
    api_keys = CLIENT.get("/api/parameters").json()["keys"]
    trame_keys = control_keys()
    assert api_keys == trame_keys == P.registry_keys()


def test_mode_filtering_consistent_across_uis():
    for mode in ("A", "B"):
        api_keys = [c["key"] for c in CLIENT.get(f"/api/parameters/mode/{mode}").json()["controls"]]
        trame_keys = control_keys(mode)
        assert api_keys == trame_keys
