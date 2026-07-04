"""Frontend runtime config: public share URLs (when a tunnel is running) so each
UI can show a Share panel and a switch-to-the-other-UI button."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api")
_PUB = Path(__file__).resolve().parents[2] / "outputs" / "public_urls.json"


@router.get("/config")
def config() -> dict:
    pub: dict = {}
    if _PUB.exists():
        try:
            pub = json.loads(_PUB.read_text())
        except Exception:  # noqa: BLE001
            pub = {}
    return {
        "app": "3Dorth",
        "react_url": pub.get("react_url"),
        "trame_url": pub.get("trame_url"),
        "public": bool(pub.get("react_url") or pub.get("trame_url")),
    }
