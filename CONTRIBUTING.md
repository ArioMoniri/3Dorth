# Contributing

## The parity rule (non-negotiable)
This project ships **two frontends over one core**. Features do not live in a UI;
they live in `core/`. Any feature or parameter change must:

1. **Land in `core/`** — the analysis logic, framework-agnostic, returns data.
2. **Be registered** — if it is configurable, add a `ParamSpec` to
   `core/parameters.py`. Both UIs render controls from `REGISTRY`, so a new
   parameter appears in both automatically.
3. **Surface in both UIs** — confirm it is reachable in `app_trame` **and**
   `app_react`. `tests/unit/test_parity.py` asserts each UI exposes exactly
   `registry_keys()`; it fails the build on drift.

### Parity checklist (paste into every PR that touches features)
- [ ] Logic added/changed in `core/` with tests.
- [ ] Configurable knobs added to `core/parameters.py` (`REGISTRY`).
- [ ] Control appears in `app_trame`.
- [ ] Control appears in `app_react`.
- [ ] `pytest tests/unit/test_parity.py` passes.
- [ ] `config.yaml` still round-trips (`scripts/watchdog.py`).

## TDD workflow (London school for new core logic)
1. Write the failing test first (`tests/unit/` or `tests/integration/`).
2. Implement the smallest thing in `core/` to pass it.
3. Refactor; keep files < 500 lines.
4. Run `make test` and `scripts/watchdog.py` before committing.

## Dev setup
```bash
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
.venv/bin/pytest -q
.venv/bin/python scripts/watchdog.py
```

## Smoke checklist (run before opening a PR)
- [ ] `make test` (or `.venv/bin/pytest -q`) green.
- [ ] `python scripts/watchdog.py` GREEN.
- [ ] `cd app_react && npm run build` exits 0.
- [ ] `python -c "import app_trame.app"` constructs without error.
- [ ] Every button/control you touched actually does something — no placeholders.
- [ ] Update `CHANGELOG.md` under **Unreleased**.

## Changelog policy
Every user-facing change gets one line under **Unreleased** in `CHANGELOG.md`
([Keep a Changelog](https://keepachangelog.com/) format). Releases move the
Unreleased entries under a dated version heading.

## House rules
- Never commit patient data (`.gitignore` blocks the CT ZIPs and DICOM).
- Never fabricate measurements. On failure, stop and report.
- De-identify every output (no name/MRN/dates).
- This is research tooling, not a clinical diagnostic — keep that framing in docs.
- Licensed under Apache 2.0; by contributing you agree your work is under the same.
