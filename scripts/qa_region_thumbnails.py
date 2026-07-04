"""QA: region-thumbnail visual picker + live public-URL polling (trame path).

Acceptance for the two features added to BOTH frontends, exercised on the trame
(server-side) app so it validates the shipped code path — NOT a reimplementation.
Does NOT launch the long-running trame server.

  1. THUMBNAILS: load the demo, drive the real ``load_region_thumbnails`` for the
     demo RIGHT side, and assert it returns per-region previews whose ``thumb``
     URLs point at real PNG files on disk (served from /downloads). Also asserts
     the file the pipeline wrote actually exists and is non-empty.
  2. CACHE: a second load for the same (session, side) is served from cache (no
     re-render) and returns the identical list.
  3. SELECT: clicking a region (``select_region``) stores ``region_label`` and
     schedules a recompute (supersede id advances).
  4. LIVE CONFIG: writing a fresh public_urls.json and calling ``refresh_config``
     updates the Share-panel state; the background poll loop picks up a change.

Runs fully offscreen.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pyvista as pv  # noqa: E402

pv.OFF_SCREEN = True

import app_trame.app as app  # noqa: E402


def _wait(cond, timeout=120.0, poll=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(poll)
    return False


def main() -> None:
    if app.DEMO_ZIP is None:
        raise SystemExit("No demo dataset found; cannot run region-thumbnail QA.")

    # --- Load the bilateral demo so a 'right' side exists. --------------------
    app._load_source(app.DEMO_ZIP, layout="bilateral")
    with app.state:
        app._refresh_session_ui()
    assert "right" in app._side_names(), (
        f"demo did not split into a right side: {app._side_names()}")
    app.state.mode = "A"
    app.state.side = "right"

    # --- 1. Thumbnails for the RIGHT side. ------------------------------------
    app.load_region_thumbnails()
    ok = _wait(lambda: not app.state.region_thumbs_loading
               and len(app.state.region_thumbs) > 0, timeout=180.0)
    thumbs = list(app.state.region_thumbs)
    assert ok and thumbs, (
        f"no region thumbnails produced (msg={app.state.region_thumbs_msg!r})")

    # Every entry carries the required fields; at least one has a real image.
    img_paths = []
    for t in thumbs:
        assert {"label", "volume_cm3", "boneness", "thumb"} <= set(t), t
        if t["thumb"]:
            assert t["thumb"].startswith("/downloads/"), t["thumb"]
            fn = Path(t["thumb"]).name
            disk = app.EXPORTS_DIR / fn
            assert disk.exists() and disk.stat().st_size > 0, (
                f"thumbnail file missing/empty: {disk}")
            img_paths.append(disk)
    assert img_paths, "no region produced a rendered image path"
    print(f"[1] right-side thumbnails: {len(thumbs)} region(s), "
          f"{len(img_paths)} rendered image path(s) on disk")
    print(f"    e.g. {img_paths[0]} ({img_paths[0].stat().st_size:,} bytes)")

    # --- 2. Cache: a second load returns the same list without re-render. -----
    app.state.region_thumbs_loading = True  # prove the cache path clears it
    app.load_region_thumbnails()
    assert not app.state.region_thumbs_loading, "cache path did not resolve sync"
    assert [t["label"] for t in app.state.region_thumbs] == \
        [t["label"] for t in thumbs], "cached thumbnails differ"
    print("[2] second load served from cache (no re-render)")

    # --- 3. Select a region -> stores label + schedules a recompute. ----------
    req_before = app._REQ_COUNTER
    target_label = thumbs[0]["label"]
    app.select_region(target_label)
    assert app.state.region_label == int(target_label), (
        f"region_label not set: {app.state.region_label}")
    assert app._DEBOUNCE_TIMER is not None, "select_region did not schedule a recompute"
    if app._DEBOUNCE_TIMER is not None:
        app._DEBOUNCE_TIMER.cancel()  # don't actually run it in QA
    print(f"[3] select_region({target_label}) set region_label and scheduled recompute")

    # --- 4. Live public-URL refresh. ------------------------------------------
    pub = app.PUBLIC_URLS
    backup = pub.read_text() if pub.exists() else None
    try:
        pub.parent.mkdir(parents=True, exist_ok=True)
        pub.write_text(json.dumps({
            "react_url": "https://qa-react.example.dev",
            "trame_url": "https://qa-trame.example.dev",
        }))
        app.refresh_config()
        assert app.state.cfg_public is True, "cfg_public not set after refresh"
        assert app.state.share_url == "https://qa-trame.example.dev", app.state.share_url
        assert app.state.other_ui_url == "https://qa-react.example.dev", app.state.other_ui_url
        print("[4] refresh_config picked up the new tunnel URLs "
              f"(share={app.state.share_url})")

        # The background poll loop should also detect a change.
        app.start_config_poll()
        pub.write_text(json.dumps({
            "react_url": "https://qa-react-2.example.dev",
            "trame_url": "https://qa-trame-2.example.dev",
        }))
        changed = _wait(
            lambda: app.state.share_url == "https://qa-trame-2.example.dev",
            timeout=app.CONFIG_POLL_S * 3)
        app._config_poll_stop.set()
        assert changed, "poll loop did not refresh the share URL live"
        print("[4b] background poll loop refreshed the URL live (no reload)")
    finally:
        if backup is not None:
            pub.write_text(backup)
        elif pub.exists():
            pub.unlink()

    print("\nQA PASS: region-thumbnail visual picker returns real image paths for "
          "the demo right side, caches per-side, selecting recomputes, and the "
          "Share panel refreshes its public URL live.")


if __name__ == "__main__":
    main()
