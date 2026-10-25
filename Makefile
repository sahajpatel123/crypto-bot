# Developer entry points. `make setup` is the one command from a fresh clone.
# Targets shell out to setup.sh so there is exactly one install path.

.PHONY: setup test lint

setup:
	./setup.sh

test:
	.venv/bin/pytest tests/unit -q

lint:
	.venv/bin/ruff check src tests
