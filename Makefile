.PHONY: setup test lint watchdog run down demo figure

setup:
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -r requirements.txt

test:
	.venv/bin/python -m pytest -q

lint:
	.venv/bin/ruff check . || true

watchdog:
	.venv/bin/python scripts/watchdog.py

demo:
	.venv/bin/python scripts/build_demo_bundle.py

figure:
	.venv/bin/python scripts/export_figure.py

run:
	./run.sh both

down:
	./run.sh down
