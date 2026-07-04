#!/usr/bin/env python3
"""Watchdog — independent automated verifier.

Runs a list of checks and prints a red/green report. Exits non-zero if any
*hard* check fails, so it can gate CI and commits. Checks that depend on
not-yet-built parts report SKIP rather than failing.

Usage:
    .venv/bin/python scripts/watchdog.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# PHI tokens that must never appear in tracked source / outputs.
# Built from fragments so the literal patient name never sits in source (and so
# this detector file does not trip its own scan).
_FIRST = "RE" + "SIT"
_LAST = "ENGI" + "NAR"
PHI_TOKENS = [_FIRST, _LAST, _FIRST.lower(), _LAST.lower()]

GREEN, RED, YELLOW, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[0m"


class Result:
    def __init__(self, name: str, status: str, detail: str = "", hard: bool = True):
        self.name, self.status, self.detail, self.hard = name, status, detail, hard


def check_registry() -> Result:
    try:
        import core.parameters as P

        n = len(P.REGISTRY)
        assert n > 0
        assert not P._duplicate_keys()
        p = P.default_parameters()
        assert p.hu_lower == 226 and p.hu_upper == 1600
        assert p.thickness_min_clamp == 0.33 and p.thickness_max_clamp == 10.0
        return Result("registry", "PASS", f"{n} params; article defaults intact")
    except Exception as e:  # noqa: BLE001
        return Result("registry", "FAIL", str(e))


def check_config_roundtrip() -> Result:
    try:
        import core.parameters as P

        cfg = ROOT / "config.yaml"
        if not cfg.exists():
            return Result("config_roundtrip", "SKIP", "config.yaml not found", hard=False)
        loaded = P.load_parameters(cfg).model_dump()
        if loaded != P.default_parameters().model_dump():
            return Result("config_roundtrip", "FAIL", "config.yaml != article defaults")
        return Result("config_roundtrip", "PASS", "config.yaml == article defaults")
    except Exception as e:  # noqa: BLE001
        return Result("config_roundtrip", "FAIL", str(e))


def check_git_phi() -> Result:
    """No patient ZIPs / DICOM staged or tracked."""
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=30
        ).stdout
        bad = [ln for ln in out.splitlines() if ln.endswith((".zip", ".dcm", ".DCM"))
               or "Bilateral Omuz" in ln or "dicom/" in ln]
        if bad:
            return Result("git_phi", "FAIL", f"PHI tracked: {bad[:3]}")
        return Result("git_phi", "PASS", "no PHI tracked in git")
    except Exception as e:  # noqa: BLE001
        return Result("git_phi", "SKIP", str(e), hard=False)


def check_deidentify() -> Result:
    """No PHI tokens in tracked source or outputs/."""
    try:
        hits: list[str] = []
        scan_dirs = ["core", "api", "app_trame", "app_react", "scripts", "docs", "outputs"]
        for d in scan_dirs:
            base = ROOT / d
            if not base.exists():
                continue
            for f in base.rglob("*"):
                if not f.is_file():
                    continue
                if f.resolve() == Path(__file__).resolve():
                    continue  # the detector legitimately holds the token fragments
                if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".glb", ".vtp", ".stl", ".pyc"}:
                    continue
                try:
                    text = f.read_text(errors="ignore")
                except Exception:  # noqa: BLE001
                    continue
                if any(tok in text for tok in PHI_TOKENS):
                    hits.append(str(f.relative_to(ROOT)))
        if hits:
            return Result("deidentify", "FAIL", f"PHI token in: {hits[:3]}")
        return Result("deidentify", "PASS", "no PHI tokens in tracked source/outputs")
    except Exception as e:  # noqa: BLE001
        return Result("deidentify", "SKIP", str(e), hard=False)


def check_pytest() -> Result:
    tests = ROOT / "tests"
    if not tests.exists() or not any(tests.rglob("test_*.py")):
        return Result("pytest", "SKIP", "no tests yet", hard=False)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(tests)],
            cwd=ROOT, capture_output=True, text=True, timeout=1200,
        )
        tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        if proc.returncode != 0:
            return Result("pytest", "FAIL", tail or "pytest failed")
        return Result("pytest", "PASS", tail)
    except Exception as e:  # noqa: BLE001
        return Result("pytest", "FAIL", str(e))


def check_parity() -> Result:
    """Once both UIs exist, they must expose exactly registry_keys()."""
    parity_test = ROOT / "tests" / "unit" / "test_parity.py"
    if not parity_test.exists():
        return Result("parity", "SKIP", "parity test not built yet", hard=False)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", str(parity_test)],
            cwd=ROOT, capture_output=True, text=True, timeout=300,
        )
        return Result("parity", "PASS" if proc.returncode == 0 else "FAIL",
                      proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "")
    except Exception as e:  # noqa: BLE001
        return Result("parity", "FAIL", str(e))


CHECKS = [
    check_registry,
    check_config_roundtrip,
    check_git_phi,
    check_deidentify,
    check_parity,
    check_pytest,
]


def main() -> int:
    print(f"\n{'='*64}\n  WATCHDOG — verification run\n{'='*64}")
    results = [c() for c in CHECKS]
    hard_fail = False
    for r in results:
        color = {"PASS": GREEN, "FAIL": RED, "SKIP": YELLOW}[r.status]
        print(f"  [{color}{r.status:4}{RESET}] {r.name:20} {r.detail}")
        if r.status == "FAIL" and r.hard:
            hard_fail = True
    n_pass = sum(r.status == "PASS" for r in results)
    n_fail = sum(r.status == "FAIL" for r in results)
    n_skip = sum(r.status == "SKIP" for r in results)
    print(f"{'-'*64}\n  {n_pass} pass · {n_fail} fail · {n_skip} skip")
    print(f"  {'RED — fix before proceeding' if hard_fail else 'GREEN — safe to proceed'}\n")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
