"""Single place the trame UI reads its control specs from — the registry.

The trame control panel is built by iterating ``control_specs()``; the React UI
does the same via the API's ``/api/parameters``. ``tests/unit/test_parity.py``
asserts both sources equal ``core.parameters.registry_keys()``, so the two
frontends cannot drift.
"""

from __future__ import annotations

import core.parameters as P


def control_specs(mode: str | None = None) -> list[dict]:
    return P.control_dicts(mode)


def control_keys(mode: str | None = None) -> list[str]:
    return [c["key"] for c in control_specs(mode)]
