#!/usr/bin/env bash
# One command from a fresh clone.
#
#   ./setup.sh            (or: make setup)
#
# Checks for Python 3.12-3.14, installs uv into ~/.local/bin only when it is
# absent, runs the locked developer sync, then proves the install with
# `cryptobot doctor` and `cryptobot selftest` before printing the exact next
# steps. Idempotent: a second run installs and changes nothing.
#
# No secrets are read, written or printed here; credentials are entered
# interactively by `cryptobot keys set`. The only network access beyond the
# package index is the uv installer, and only when uv is missing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

VENV=".venv"
DOCTOR_CONFIG="configs/paper.toml"

say() { printf '%s\n' "$*"; }
fail() { printf 'setup: FAIL %s\n' "$*" >&2; exit 1; }

# --- 1. Python 3.12-3.14 (pyproject: requires-python = ">=3.12,<3.15") ------
python_fits() {
    "$1" -c 'import sys; sys.exit(0 if (3, 12) <= sys.version_info[:2] <= (3, 14) else 1)' \
        >/dev/null 2>&1
}

find_python() {
    local candidate
    for candidate in python3.12 python3.13 python3.14 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && python_fits "$candidate"; then
            printf '%s' "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"

# --- 2. uv, into ~/.local/bin, only when absent ----------------------------
export PATH="$HOME/.local/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
    say "setup: uv present ($(uv --version))"
else
    say "setup: installing uv into $HOME/.local/bin"
    command -v curl >/dev/null 2>&1 \
        || fail "curl is required to install uv (install uv or curl, then re-run)"
    curl -LsSf https://astral.sh/uv/install.sh | sh \
        || fail "the uv installer failed; install uv from https://docs.astral.sh/uv/ and re-run"
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null 2>&1 \
        || fail "uv is still not on PATH after installing to $HOME/.local/bin"
    say "setup: uv installed ($(uv --version))"
fi

# --- 3. A 3.12-3.14 interpreter (uv may provision one) ---------------------
if [ -z "$PYTHON" ]; then
    say "setup: no Python 3.12-3.14 on PATH; asking uv for a managed 3.12"
    if uv python install 3.12 >/dev/null 2>&1; then
        PYTHON="$(uv python find 3.12 2>/dev/null || true)"
    fi
    if [ -z "$PYTHON" ] || ! python_fits "$PYTHON"; then
        fail "needs Python 3.12, 3.13 or 3.14 (found ${PYTHON:-none}; $(command -v python3 >/dev/null 2>&1 && python3 -V 2>&1 || echo 'no python3')). Install one (for example 'uv python install 3.12'), then re-run."
    fi
fi
say "setup: python $("$PYTHON" -V 2>&1) ($PYTHON)"

# --- 4. Never create a virtualenv inside a path git tracks -----------------
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if git ls-files --error-unmatch "$VENV" >/dev/null 2>&1; then
        fail "$VENV is tracked by git; refusing to create a virtualenv there"
    fi
    if ! git check-ignore -q "$VENV"; then
        fail "$VENV is not git-ignored in this checkout; refusing to create a virtualenv inside the work tree"
    fi
fi

# --- 5. Locked developer install -------------------------------------------
say "setup: uv sync --locked --extra dev"
uv sync --locked --extra dev \
    || fail "uv sync --locked failed (see the output above)"

CRYPTOBOT="$VENV/bin/cryptobot"
[ -x "$CRYPTOBOT" ] \
    || fail "uv sync did not produce $VENV/bin/cryptobot; the install is incomplete"

# --- 6. Prove the install, fail fast and readable --------------------------
say "setup: $CRYPTOBOT doctor --config $DOCTOR_CONFIG"
"$CRYPTOBOT" doctor --config "$DOCTOR_CONFIG" \
    || fail "cryptobot doctor reported a problem (see the output above)"

say "setup: $CRYPTOBOT selftest"
"$CRYPTOBOT" selftest \
    || fail "cryptobot selftest reported a problem (see the output above)"

# --- 7. Next steps ---------------------------------------------------------
say ""
say "setup: READY (doctor + selftest passed)"
say ""
say "next steps, in order:"
say "  1. store the demo/live API key without echoing it:"
say "       $CRYPTOBOT keys set             # or: --backend keychain on macOS"
say "  2. confirm where it is stored (booleans only):"
say "       $CRYPTOBOT keys status"
say "  3. prove the key's permissions before trading:"
say "       $CRYPTOBOT keys check --market futures --require-ip"
say "  4. run the demo drill:"
say "       $CRYPTOBOT demo-drill --help"
say "  5. guided human-only steps (host check, legal, tax):"
say "       $CRYPTOBOT owner"
say ""
say "gate: NO-GO until a real demo drill passes and the owner arms. no demonstrated edge"
