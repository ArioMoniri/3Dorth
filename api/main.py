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


# Native / no-Docker mode: serve the built React SPA from THIS process so the whole
# app runs on ONE port with NO nginx (the UI's /api calls hit the routes above on the
# same origin). Mounted LAST so every /api route still wins. Reliable WITHOUT any env
# var: default to <repo>/app_react/dist (absolute, CWD-independent) whenever a build
# exists; THREEDORTH_STATIC_DIR only overrides the location. The Docker/K8s deploys
# serve the SPA via nginx and simply have no dist here, so this stays inert for them.
def _resolve_static_dir() -> Path | None:
    override = os.environ.get("THREEDORTH_STATIC_DIR", "").strip()
    candidate = Path(override) if override else (ROOT / "app_react" / "dist")
    return candidate if (candidate / "index.html").is_file() else None


class _SpaStatic(StaticFiles):
    """Serve the built SPA with correct caching so a redeploy is picked up WITHOUT
    a manual hard-refresh: ``index.html`` must always be revalidated (else the
    browser keeps an old copy that points at stale hashed bundles — the classic
    "my changes don't show" trap), while the content-hashed ``assets/*`` are
    immutable and cache forever."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        try:
            p = str(path)
            if p in ("", ".", "/", "index.html") or p.endswith(".html"):
                resp.headers["Cache-Control"] = "no-cache, must-revalidate"
            elif "assets/" in p:
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        except Exception:
            pass
        return resp


_STATIC_DIR = _resolve_static_dir()
if _STATIC_DIR is not None:
    app.mount("/", _SpaStatic(directory=str(_STATIC_DIR), html=True), name="ui")
    print(f"[3Dorth] serving the React UI at / from {_STATIC_DIR}", flush=True)
else:
    print("[3Dorth] React UI NOT served at / — no build found at app_react/dist "
          "(GET / will 404). Build it:  cd app_react && npm run build  "
          "(scripts/run_native.sh does this automatically).", flush=True)
