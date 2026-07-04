#!/usr/bin/env python3
"""Capture real screenshots of the running UIs for the README (Playwright).

Assumes the API (:8000), React (:5173), and trame (:8081) are already running.
Writes PNGs into docs/assets/.

Usage:
    .venv/bin/python scripts/capture_ui.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

GL = ["--use-gl=swiftshader", "--ignore-gpu-blocklist", "--enable-webgl",
      "--use-angle=swiftshader"]


def _click(page, name):
    try:
        page.get_by_role("button", name=name, exact=True).first.click(timeout=4000)
        return True
    except Exception:  # noqa: BLE001
        return False


def capture_react(pw):
    b = pw.chromium.launch(args=GL)
    pg = b.new_page(viewport={"width": 1512, "height": 950}, device_scale_factor=1.5)
    # the app polls /api/config forever, so networkidle never fires
    pg.goto("http://localhost:5173/", wait_until="domcontentloaded", timeout=60000)
    time.sleep(4)
    _click(pg, "Left")            # isolated humerus: faster + cleaner
    time.sleep(26)                # wait out the ~5-20 s recompute
    pg.screenshot(path=str(OUT / "ui_react_thickness.png"))
    print("wrote ui_react_thickness.png")
    # Mode B deviation
    if _click(pg, "Mode B"):
        time.sleep(2)
        _click(pg, "Deviation")
        time.sleep(2)
        _click(pg, "Compute deviation") or _click(pg, "Compute")
        time.sleep(70)            # registration + deviation is slower
        pg.screenshot(path=str(OUT / "ui_react_deviation.png"))
        print("wrote ui_react_deviation.png")
    b.close()


def capture_trame(pw):
    b = pw.chromium.launch(args=GL)
    pg = b.new_page(viewport={"width": 1512, "height": 950}, device_scale_factor=1.5)
    pg.goto("http://localhost:8081/", wait_until="networkidle", timeout=60000)
    time.sleep(35)                # trame connects its WS + bootstraps a compute
    pg.screenshot(path=str(OUT / "ui_trame.png"))
    print("wrote ui_trame.png")
    b.close()


def main() -> int:
    with sync_playwright() as pw:
        try:
            capture_react(pw)
        except Exception as e:  # noqa: BLE001
            print(f"React capture failed: {e}")
        try:
            capture_trame(pw)
        except Exception as e:  # noqa: BLE001
            print(f"trame capture failed: {e}")
    for f in ("ui_react_thickness.png", "ui_react_deviation.png", "ui_trame.png"):
        p = OUT / f
        print(f"  {f}: {'OK ' + str(p.stat().st_size // 1024) + ' KB' if p.exists() else 'MISSING'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
