"""Regression tests for the native one-process UI mount.

The bug: ``GET /`` returned 404 even though ``app_react/dist/index.html`` existed,
because the SPA was only mounted when the ``THREEDORTH_STATIC_DIR`` env var was set —
and a cached-build restart could launch uvicorn without it. The fix makes the app
auto-serve ``<repo>/app_react/dist`` whenever a build exists, with the env var only
overriding the location. These tests pin that behaviour so it can't regress.
"""

from __future__ import annotations

import importlib

import pytest

import api.main


def test_resolve_prefers_env_override(tmp_path, monkeypatch):
    """THREEDORTH_STATIC_DIR points the mount at any dir that has an index.html."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>ok")
    monkeypatch.setenv("THREEDORTH_STATIC_DIR", str(dist))
    assert api.main._resolve_static_dir() == dist

    # A dir without index.html is not servable -> None (clear "no UI" signal).
    (dist / "index.html").unlink()
    assert api.main._resolve_static_dir() is None


def test_resolve_default_is_repo_dist(monkeypatch):
    """With no env var, the default candidate is <repo>/app_react/dist (CWD-independent)."""
    monkeypatch.delenv("THREEDORTH_STATIC_DIR", raising=False)
    got = api.main._resolve_static_dir()
    # Either a real build exists here (returns that exact path) or it doesn't (None);
    # in both cases the resolver must never point somewhere other than the repo dist.
    assert got is None or got == api.main.ROOT / "app_react" / "dist"


def test_root_serves_index_html_when_build_exists(tmp_path, monkeypatch):
    """GET / returns index.html (200) and /api routes are NOT shadowed by the mount."""
    dist = tmp_path / "dist"
    dist.mkdir()
    marker = "3DORTH-TEST-UI-MARKER"
    (dist / "index.html").write_text(f"<!doctype html><title>3Dorth</title>{marker}")
    monkeypatch.setenv("THREEDORTH_STATIC_DIR", str(dist))

    # The mount is evaluated at import time, so reload the module with the env set.
    module = importlib.reload(api.main)
    try:
        from fastapi.testclient import TestClient

        client = TestClient(module.app)

        root = client.get("/")
        assert root.status_code == 200, "GET / must serve the SPA, not 404"
        assert marker in root.text

        # /api still wins (mounted before the catch-all SPA mount).
        assert client.get("/api/health").json()["status"] == "ok"
    finally:
        # Restore the default app so the rest of the suite sees an unmodified module.
        monkeypatch.delenv("THREEDORTH_STATIC_DIR", raising=False)
        importlib.reload(api.main)


def test_no_build_means_no_root_mount(tmp_path, monkeypatch):
    """With no build anywhere, GET / honestly 404s (and startup warns) — never a crash."""
    empty = tmp_path / "nope"  # does not exist
    monkeypatch.setenv("THREEDORTH_STATIC_DIR", str(empty))
    module = importlib.reload(api.main)
    try:
        assert module._STATIC_DIR is None
        from fastapi.testclient import TestClient

        client = TestClient(module.app)
        assert client.get("/").status_code == 404
        assert client.get("/api/health").json()["status"] == "ok"
    finally:
        monkeypatch.delenv("THREEDORTH_STATIC_DIR", raising=False)
        importlib.reload(api.main)
