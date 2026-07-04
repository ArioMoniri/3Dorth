"""3Dorth API — exposes the core registry and demo geometry to the React SPA.

Deliberately thin: it serves data produced by ``core`` (and the offline demo
bundle). All analysis lives in ``core``; this module must contain none.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.routers import config, demo, parameters, session  # noqa: E402

app = FastAPI(title="3Dorth API", version="0.0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(parameters.router)
app.include_router(demo.router)
app.include_router(session.router)
app.include_router(config.router)

_DEMO_DIR = ROOT / "outputs" / "demo"
if _DEMO_DIR.exists():
    app.mount("/api/geometry", StaticFiles(directory=str(_DEMO_DIR)), name="geometry")

_SESSION_DIR = ROOT / "outputs" / "sessions"
_SESSION_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/session-geometry", StaticFiles(directory=str(_SESSION_DIR)), name="session-geometry")

_EXPORTS_DIR = ROOT / "outputs" / "exports"
_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/api/exports", StaticFiles(directory=str(_EXPORTS_DIR)), name="exports")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


# Native / no-Docker mode: serve the built React SPA from this same process so the
# whole app runs on ONE port with NO nginx (the UI's /api calls hit these routes on
# the same origin). Mounted LAST so every /api route above still wins. Set
# THREEDORTH_STATIC_DIR=app_react/dist (scripts/run_native.sh does this). Ignored by
# the Docker/K8s deploys, which serve the SPA via nginx.
_STATIC_DIR = os.environ.get("THREEDORTH_STATIC_DIR", "").strip()
if _STATIC_DIR and Path(_STATIC_DIR).is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")
