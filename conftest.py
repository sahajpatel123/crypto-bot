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


import pytest  # noqa: E402


def _tree_bytes(root: Path) -> int:
    total = 0
    for p in root.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            pass
    return total


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    """Print how much pytest scratch this run left behind (visibility only).

    Runs as the outermost wrapper, so the measurement is taken AFTER pytest's
    own retention-policy cleanup: it is the residual size on disk.
    """
    try:
        return (yield)
    finally:
        try:
            factory = getattr(session.config, "_tmp_path_factory", None)
            base = getattr(factory, "_basetemp", None)
            if base is not None and Path(base).exists():
                mb = _tree_bytes(Path(base)) / 1e6
                print(f"\n[pytest scratch left in {base}: {mb:.1f} MB]")
        except Exception:  # never let a diagnostic break a run
            pass
