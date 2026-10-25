"""Make the repository root importable under the pytest console script.

CI runs the console script (``pytest tests/unit -q`` / ``.venv/bin/pytest``),
which - unlike ``python -m pytest`` - does not put the working directory on
``sys.path``. ``tests/`` is deliberately not a package (adding
``tests/__init__.py`` would change collection semantics for the whole
suite), so ``from tests.unit... import ...`` and ``import tools.run_budget``
only resolve when the root itself is importable.

Inserting it here makes the console script behave exactly like
``python -m pytest`` without touching collection.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
