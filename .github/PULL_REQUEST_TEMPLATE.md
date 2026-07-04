<!-- Keep PRs small and verified. -->

## What and why
<!-- One or two sentences. Link the issue. -->

## Parity checklist (features touching analysis or parameters)
- [ ] Logic added/changed in `core/` with tests.
- [ ] Configurable knobs added to `core/parameters.py` (registry).
- [ ] Control appears in `app_trame` **and** `app_react`.
- [ ] `pytest tests/unit/test_parity.py` passes.
- [ ] `config.yaml` still round-trips (`python scripts/watchdog.py`).

## Verification
- [ ] `make test` green.
- [ ] `python scripts/watchdog.py` GREEN.
- [ ] No fabricated numbers; no PHI in code/outputs/tests.
- [ ] `CHANGELOG.md` updated under Unreleased.
