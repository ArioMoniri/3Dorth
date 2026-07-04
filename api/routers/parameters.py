"""Parameter-registry endpoints. The React UI renders its control panel from
these, exactly as the trame UI renders from ``core.parameters`` directly — this
is what keeps the two frontends at parity."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

import core.parameters as P

router = APIRouter(prefix="/api")


@router.get("/parameters")
def get_parameters() -> dict:
    return {
        "keys": P.registry_keys(),
        "controls": P.control_dicts(),
        "defaults": P.default_parameters().model_dump(),
    }


@router.get("/parameters/mode/{mode}")
def get_parameters_for_mode(mode: str) -> dict:
    if mode not in ("A", "B"):
        raise HTTPException(400, "mode must be 'A' or 'B'")
    return {"controls": P.control_dicts(mode)}
