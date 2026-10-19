"""Recorded venue fixtures: ingest validation + contract cases (F2.3)."""
from __future__ import annotations

from pathlib import Path

RECORDED_DIR = Path("tests/fixtures/recorded")

EXPECTED = ("account.json", "income.json", "openOrders.json",
            "openAlgoOrders.json", "leverageBracket.json",
            "commissionRate.json")

SECRET_FIELDS = frozenset({
    "apikey", "api_key", "apisecret", "api_secret", "secret",
    "secretkey", "secret_key", "signature", "x-mbx-apikey",
    "privatekey", "private_key"})

_PEM_MARK = "PRIVATE KEY"


class FixtureRefused(ValueError):
    pass


def _scan_secrets(node, path="") -> list[str]:
    hits: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if str(key).lower() in SECRET_FIELDS and value:
                hits.append(here)
            hits.extend(_scan_secrets(value, here))
    elif isinstance(node, list):
        for i, value in enumerate(node):
            hits.extend(_scan_secrets(value, f"{path}[{i}]"))
    elif isinstance(node, str) and _PEM_MARK in node:
        hits.append(path or "<root>")
    return hits


def _num(value, name):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise FixtureRefused(f"{name} must be numeric, got {value!r}") from None


def validate_account(doc, name="account.json") -> None:
    if not isinstance(doc, dict):
        raise FixtureRefused(f"{name}: expected an object")
    for key in ("totalWalletBalance", "totalMarginBalance"):
        if key not in doc:
            raise FixtureRefused(f"{name}: missing {key!r}")
        _num(doc[key], f"{name}.{key}")


def validate_income(doc, name="income.json") -> None:
    if not isinstance(doc, list):
        raise FixtureRefused(f"{name}: expected a list")
    for row in doc:
        if not isinstance(row, dict):
            raise FixtureRefused(f"{name}: rows must be objects")
        _num(row.get("income", 0.0), f"{name}.income")


def validate_orders(doc, name) -> None:
    if not isinstance(doc, list):
        raise FixtureRefused(f"{name}: expected a list")


def validate_brackets(doc, name="leverageBracket.json") -> None:
    from cryptobot.app.filters import FilterError, parse_brackets_payload

    entries = doc if isinstance(doc, list) else [doc]
    try:
        symbols = [str(e["symbol"]) for e in entries]
    except (KeyError, TypeError):
        raise FixtureRefused(f"{name}: entries need symbols") from None
    if not symbols:
        raise FixtureRefused(f"{name}: empty bracket set")
    try:
        parse_brackets_payload(entries, symbols)
    except (FilterError, ValueError) as exc:
        raise FixtureRefused(f"{name}: {exc}") from None


def validate_commission(doc, name="commissionRate.json") -> None:
    if not isinstance(doc, dict):
        raise FixtureRefused(f"{name}: expected an object")
    for key in ("makerCommissionRate", "takerCommissionRate"):
        if key not in doc:
            raise FixtureRefused(f"{name}: missing {key!r}")
        _num(doc[key], f"{name}.{key}")


_VALIDATORS = {
    "account.json": validate_account,
    "income.json": validate_income,
    "openOrders.json": lambda d: validate_orders(d, "openOrders.json"),
    "openAlgoOrders.json": lambda d: validate_orders(
        d, "openAlgoOrders.json"),
    "leverageBracket.json": validate_brackets,
    "commissionRate.json": validate_commission,
}


def ingest(src_dir: str | Path, *, force: bool = False) -> list[str]:
    """Validate + install a recorded-fixture directory.

    Every EXPECTED file must exist, parse, pass redaction (no
    secrets) and shape validation — all-or-nothing (a partial
    install never lands). Returns installed file names.
    """
    import json as _json

    src = Path(src_dir)
    docs: dict[str, object] = {}
    for name in EXPECTED:
        path = src / name
        if not path.exists():
            raise FixtureRefused(f"missing {name} in {src}")
        try:
            docs[name] = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FixtureRefused(f"{name}: unreadable ({exc})") from None
        hits = _scan_secrets(docs[name])
        if hits:
            raise FixtureRefused(
                f"{name}: possible secrets at {hits} — redact and retry")
        _VALIDATORS[name](docs[name])
    target = Path(RECORDED_DIR)
    if target.exists() and any(target.iterdir()) and not force:
        raise FixtureRefused(f"{target} is not empty (use --force)")
    target.mkdir(parents=True, exist_ok=True)
    for name in EXPECTED:
        (target / name).write_text(
            _json.dumps(docs[name], indent=1, sort_keys=True) + "\n",
            encoding="utf-8")
    return list(EXPECTED)


def recorded_contract_cases(
        root: str | Path | None = None) -> list[dict]:
    """Contract cases auto-activated by installed fixtures ([] when absent)."""
    import json as _json

    base = Path(root) if root is not None else Path(RECORDED_DIR)
    cases = []
    for name in EXPECTED:
        path = base / name
        if not path.exists():
            continue
        try:
            doc = _json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cases.append({"name": name[:-len(".json")], "path": str(path),
                      "doc": doc})
    return cases


def check_recorded_case(case: dict) -> None:
    """Re-validate one installed case (contract must hold on disk too)."""
    name = f"{case['name']}.json"
    _VALIDATORS[name](case["doc"])
