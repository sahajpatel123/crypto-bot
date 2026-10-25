"""`cryptobot keys`: secret-safe entry, status and the pre-trade check.

The check answers one question before any order can be sent: does this API
key hold only the permissions this bot needs? It signs
``GET /sapi/v1/account/apiRestrictions`` with the same HMAC-SHA256 helper the
order path uses (``binance_live.sign_params``) and reads the venue's own
answer:

* withdrawals must be OFF, and so must universal and internal transfer;
* reading must be ON;
* spot and/or USD-M futures trading must be ON per ``--market``;
* ``ipRestrict`` must be ON (``--require-ip`` is on by default).

Exit codes: ``0`` every rule holds, ``2`` a permission violation (or missing
credentials), ``3`` the venue was unreachable or refused the key. A 401 or
``-2015`` is an auth failure, never a pass.

The transport is injectable (``check_permissions(..., transport=...)``) so
every rule has a hermetic unit test.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any

from cryptobot.ops import credentials

# /sapi/* lives on the spot REST host, not on the USD-M futures host.
SPOT_REST_URL = "https://api.binance.com"
# The demo profile is checked against the demo host configs/demo.toml uses,
# never against production. Unverified from a geo-blocked network: an
# unsupported endpoint fails closed (exit 3), it can never report a pass.
DEMO_REST_URL = "https://demo-fapi.binance.com"
PROFILE_BASE_URLS = {credentials.PROFILE_PROD: SPOT_REST_URL,
                     credentials.PROFILE_DEMO: DEMO_REST_URL}
RESTRICTIONS_PATH = "/sapi/v1/account/apiRestrictions"
RECV_WINDOW_MS = 5000

DEFAULT_MARKET = "futures"
MARKETS: tuple[str, str, str] = ("spot", "futures", "both")
BACKENDS: tuple[str, str] = credentials.BACKENDS

EXIT_PASS = 0
EXIT_VIOLATION = 2
EXIT_UNAVAILABLE = 3

OUTCOME_PASS = "pass"
OUTCOME_VIOLATION = "permission-violation"
OUTCOME_AUTH = "auth-failure"
OUTCOME_NETWORK = "network-failure"
OUTCOME_MISSING = "missing-credentials"

AUTH_FAILURE_STATUSES = (401, 403)
AUTH_FAILURE_CODES = (-2014, -2015, -1022, -1099)

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_INFO = "INFO"

# Reported as INFO so an operator sees the venue's whole permission answer.
PERMISSION_KEYS: tuple[str, ...] = (
    "enableReading",
    "enableSpotAndMarginTrading",
    "enableFutures",
    "enableMargin",
    "enableVanillaOptions",
    "enablePortfolioMarginTrading",
    "enableWithdrawals",
    "enableInternalTransfer",
    "permitsUniversalTransfer",
    "enableFixApiTrade",
    "enableFixReadOnly",
    "ipRestrict",
)


@dataclass(frozen=True)
class CheckRow:
    """One line of the PASS/FAIL table. Never contains a credential."""

    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status,
                "detail": self.detail}


@dataclass(frozen=True)
class CheckReport:
    """The whole verdict, with the exit code the CLI must return."""

    rows: tuple[CheckRow, ...]
    outcome: str
    market: str = DEFAULT_MARKET
    require_ip: bool = True
    base_url: str = SPOT_REST_URL
    profile: str = credentials.PROFILE_PROD

    @property
    def failed(self) -> tuple[CheckRow, ...]:
        return tuple(r for r in self.rows if r.status == STATUS_FAIL)

    @property
    def verdict(self) -> str:
        return STATUS_PASS if not self.failed else STATUS_FAIL

    @property
    def ok(self) -> bool:
        return not self.failed and self.outcome == OUTCOME_PASS

    @property
    def exit_code(self) -> int:
        if self.outcome == OUTCOME_VIOLATION:
            return EXIT_VIOLATION
        if self.outcome in (OUTCOME_AUTH, OUTCOME_NETWORK, OUTCOME_MISSING):
            return EXIT_UNAVAILABLE
        return EXIT_PASS if not self.failed else EXIT_VIOLATION

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "outcome": self.outcome,
            "exit_code": self.exit_code,
            "profile": self.profile,
            "market": self.market,
            "require_ip": self.require_ip,
            "base_url": self.base_url,
            "endpoint": RESTRICTIONS_PATH,
            "rows": [r.as_dict() for r in self.rows],
        }


def _flag(document: dict[str, Any], key: str) -> bool:
    return bool(document.get(key))


def _market_rows(document: dict[str, Any], market: str) -> list[CheckRow]:
    rows: list[CheckRow] = []
    if market in ("spot", "both"):
        enabled = _flag(document, "enableSpotAndMarginTrading")
        rows.append(CheckRow(
            "spot-trading-enabled",
            STATUS_PASS if enabled else STATUS_FAIL,
            "spot trading is enabled on this key" if enabled else
            "spot trading is disabled on this key (want it ON for "
            "--market spot)"))
    if market in ("futures", "both"):
        enabled = _flag(document, "enableFutures")
        rows.append(CheckRow(
            "futures-trading-enabled",
            STATUS_PASS if enabled else STATUS_FAIL,
            "USD-M futures trading is enabled on this key" if enabled else
            "USD-M futures trading is disabled on this key (want it ON for "
            "the bot's venue)"))
    return rows


def evaluate_restrictions(document: dict[str, Any], *,
                          market: str = DEFAULT_MARKET,
                          require_ip: bool = True) -> tuple[CheckRow, ...]:
    """Turn the venue's apiRestrictions answer into PASS/FAIL/INFO rows."""
    if market not in MARKETS:
        raise ValueError(f"market must be one of {MARKETS}, got {market!r}")
    if not isinstance(document, dict):
        raise ValueError("apiRestrictions returned no document")
    rows: list[CheckRow] = []

    reading = _flag(document, "enableReading")
    rows.append(CheckRow(
        "api-reading", STATUS_PASS if reading else STATUS_FAIL,
        "the key can read account state" if reading else
        "reading is disabled on this key: it cannot read account state"))

    withdrawals = _flag(document, "enableWithdrawals")
    rows.append(CheckRow(
        "withdrawals-disabled", STATUS_FAIL if withdrawals else STATUS_PASS,
        "withdrawals may be drawn with this key" if withdrawals else
        "withdrawals are disabled on this key"))

    internal = _flag(document, "enableInternalTransfer")
    rows.append(CheckRow(
        "internal-transfer-disabled",
        STATUS_FAIL if internal else STATUS_PASS,
        "internal transfer is enabled on this key" if internal else
        "internal transfer is disabled on this key"))

    universal = _flag(document, "permitsUniversalTransfer")
    rows.append(CheckRow(
        "universal-transfer-disabled",
        STATUS_FAIL if universal else STATUS_PASS,
        "universal transfer is enabled on this key" if universal else
        "universal transfer is disabled on this key"))

    rows.extend(_market_rows(document, market))

    restricted = _flag(document, "ipRestrict")
    if not require_ip:
        rows.append(CheckRow(
            "ip-restrict", STATUS_INFO,
            f"ipRestrict={restricted} (not required by this run)"))
    else:
        rows.append(CheckRow(
            "ip-restrict", STATUS_PASS if restricted else STATUS_FAIL,
            "the key is bound to the owner's IP allowlist" if restricted else
            "the key is NOT IP-restricted: anyone holding it can use it "
            "from anywhere"))

    covered = {row.name for row in rows}
    for key in PERMISSION_KEYS:
        if key in covered or key not in document:
            continue
        value = document[key]
        if isinstance(value, bool):
            detail = f"venue reports {key}={str(value).lower()}"
        elif isinstance(value, int):
            detail = f"venue reports {key}={value}"
        else:
            detail = "venue reports a value this check does not read"
        rows.append(CheckRow(key, STATUS_INFO, detail))
    return tuple(rows)


def classify_failure(exc: Exception) -> str:
    """Auth failure or network failure for one transport exception."""
    from cryptobot.adapters.binance_live import VenueHttpError
    if not isinstance(exc, VenueHttpError):
        return OUTCOME_NETWORK
    if exc.status in AUTH_FAILURE_STATUSES or exc.code in AUTH_FAILURE_CODES:
        return OUTCOME_AUTH
    return OUTCOME_NETWORK


def make_transport(base_url: str = SPOT_REST_URL) -> Any:
    """The project's stdlib HTTPS transport (never a second HTTP stack)."""
    from cryptobot.adapters.binance_live import UrllibTransport
    return UrllibTransport(base_url)


def fetch_restrictions(api_key: str, api_secret: str, *,
                       transport: Any = None,
                       base_url: str = SPOT_REST_URL,
                       now_ms: int | None = None,
                       recv_window_ms: int = RECV_WINDOW_MS) -> Any:
    """Signed read of apiRestrictions over the shared transport + signer."""
    from cryptobot.adapters.binance_live import sign_params
    sender = transport if transport is not None else make_transport(base_url)
    stamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    params = sign_params(api_secret.encode("utf-8"), {},
                         timestamp_ms=stamp, recv_window_ms=recv_window_ms)
    return sender.request("GET", RESTRICTIONS_PATH, params,
                          {"X-MBX-APIKEY": api_key})


def check_permissions(api_key: str, api_secret: str, *,
                      transport: Any = None,
                      market: str = DEFAULT_MARKET,
                      require_ip: bool = True,
                      base_url: str = SPOT_REST_URL,
                      now_ms: int | None = None,
                      profile: str = credentials.PROFILE_PROD) -> CheckReport:
    """Run the pre-trade permission check. Never raises for venue errors."""
    try:
        document = fetch_restrictions(api_key, api_secret, transport=transport,
                                      base_url=base_url, now_ms=now_ms)
    except Exception as exc:  # noqa: BLE001 - every failure is a verdict.
        outcome = classify_failure(exc)
        detail = _failure_detail(exc)
        row = CheckRow(f"api-key-{outcome}", STATUS_FAIL, detail)
        return CheckReport((row,), outcome, market=market,
                           require_ip=require_ip, base_url=base_url,
                           profile=profile)
    rows = evaluate_restrictions(document, market=market,
                                 require_ip=require_ip)
    violated = any(row.status == STATUS_FAIL for row in rows)
    return CheckReport(rows,
                       OUTCOME_VIOLATION if violated else OUTCOME_PASS,
                       market=market, require_ip=require_ip,
                       base_url=base_url, profile=profile)


def _failure_detail(exc: Exception) -> str:
    name = type(exc).__name__
    status = getattr(exc, "status", None)
    code = getattr(exc, "code", None)
    message = str(getattr(exc, "msg", "") or "")
    parts = [f"{name}"]
    if status is not None:
        parts.append(f"http={status}")
    if code is not None:
        parts.append(f"code={code}")
    if message:
        parts.append(message)
    return " ".join(parts)


def prod_gate(api_key: str, api_secret: str, *,
              transport: Any = None,
              market: str = DEFAULT_MARKET,
              require_ip: bool = True) -> CheckReport:
    """The permission gate `cryptobot run --mode prod` calls before starting.

    Defaults match the owner requirement: futures enabled, IP pinning on,
    withdrawals and transfers off. A violating document (or an unreachable
    venue) keeps `Run` from ever building the order path.
    """
    return check_permissions(api_key, api_secret, transport=transport,
                             market=market, require_ip=require_ip)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _emit(report: CheckReport, *, json_mode: bool,
          redactor: credentials.Redactor) -> None:
    if json_mode:
        payload = redactor.document(report.as_dict())
        print(json.dumps(payload, indent=1, sort_keys=True))
        return
    for line in redactor.lines(_render_lines(report)):
        print(line)


def _render_lines(report: CheckReport) -> list[str]:
    lines = [f"keys check: {report.verdict} (profile={report.profile}, "
             f"market={report.market}, "
             f"require_ip={str(report.require_ip).lower()}, "
             f"endpoint={report.base_url}{RESTRICTIONS_PATH})"]
    for row in report.rows:
        lines.append(f"  [{row.status}] {row.name}: {row.detail}")
    if report.verdict != STATUS_PASS:
        lines.append(f"keys check: {report.outcome}")
    return lines


def resolve_args_store(args: argparse.Namespace
                       ) -> credentials.SecretStore:
    backend = getattr(args, "backend", None) or credentials.default_backend()
    return credentials.make_store(backend,
                                  env_path=getattr(args, "env", None))


def cmd_keys_set(args: argparse.Namespace) -> int:
    """Interactive (or piped) secret entry: validated, never echoed."""
    redactor = credentials.Redactor()
    try:
        profile = getattr(args, "profile", None) or credentials.PROFILE_PROD
        store = resolve_args_store(args)
        values, results = credentials.collect_entries(
            store,
            from_stdin=bool(getattr(args, "from_stdin", False)),
            force=bool(getattr(args, "force", False)),
            profile=profile)
    except credentials.CredentialError as exc:
        print(f"keys set: REFUSED {redactor.text(exc)}", file=sys.stderr)
        return EXIT_VIOLATION
    for name in values:
        redactor.register(values[name])
    for result in results:
        if not result.written:
            print(f"keys set: {result.name}: {result.note}")
    if not values:
        print("keys set: nothing written (existing entries kept)")
        return EXIT_PASS
    try:
        written = credentials.write_credentials(store, values,
                                                profile=profile)
    except credentials.CredentialError as exc:
        print(f"keys set: REFUSED {redactor.text(exc)}", file=sys.stderr)
        return EXIT_VIOLATION
    print(f"keys set: profile={profile}")
    for result in written:
        print(f"keys set: {result.name}: {result.note} (value not shown)")
    if isinstance(store, credentials.DotenvStore):
        safety = store.safety()
        mode = store.mode()
        print(f"keys set: dotenv {safety.describe()} "
              f"(mode={oct(mode) if mode is not None else 'unknown'})")
        if not safety.safe:
            print("keys set: WARNING the dotenv path is not safe; move the "
                  "secrets or use --backend keychain", file=sys.stderr)
            return EXIT_VIOLATION
    print("keys set: next run `cryptobot keys status`, then "
          "`cryptobot keys check`")
    return EXIT_PASS


def cmd_keys_status(args: argparse.Namespace) -> int:
    """Presence and backend only: no value, prefix or suffix, ever."""
    status = credentials.status(
        env_path=getattr(args, "env", None),
        profile=getattr(args, "profile", None) or credentials.PROFILE_PROD)
    document = credentials.redact_document(status.as_dict())
    if getattr(args, "json", False):
        print(json.dumps(document, indent=1, sort_keys=True))
    else:
        print(_render_status(status))
    safe = status.complete and not status.insecure
    return EXIT_PASS if safe else EXIT_VIOLATION


def _render_status(status: credentials.CredentialStatus) -> str:
    lines = [f"keys status: backend={status.backend}",
             f"  dotenv: {status.dotenv_safety.describe()}"]
    if status.dotenv_mode is not None:
        lines.append(f"  dotenv-mode: {oct(status.dotenv_mode)}")
    for profile in status.profiles:
        mark = "selected" if profile.profile == status.profile else "other"
        lines.append(f"  profile {profile.profile} ({mark}):")
        for entry in profile.sources:
            state = "present" if entry.present else "missing"
            lines.append(f"    {entry.name}: {state} (source={entry.source})")
    if status.complete and not status.insecure:
        lines.append(f"keys status: OK profile {status.profile} is complete "
                     f"and storage is safe")
    elif not status.complete:
        lines.append(f"keys status: MISSING profile {status.profile}: "
                     + ", ".join(status.missing)
                     + f" (run `cryptobot keys set --profile {status.profile}`)")
    else:
        lines.append("keys status: INSECURE the dotenv file holding these "
                     "secrets is not safely ignored by git")
    return "\n".join(lines)


def run_check(args: argparse.Namespace, *, transport: Any = None) -> int:
    """`keys check` with an injectable transport (tests stay offline)."""
    redactor = credentials.Redactor()
    profile = getattr(args, "profile", None) or credentials.PROFILE_PROD
    market = getattr(args, "market", DEFAULT_MARKET)
    require_ip = bool(getattr(args, "require_ip", True))
    base_url = (getattr(args, "base_url", None)
                or PROFILE_BASE_URLS[profile])
    resolved = credentials.load_credentials(
        profile=profile, env_path=getattr(args, "env", None))
    if resolved.missing:
        report = CheckReport(
            (CheckRow("credentials", STATUS_FAIL,
                      f"profile {profile} is missing "
                      + ", ".join(resolved.missing)
                      + f" (run `cryptobot keys set --profile {profile}`)"),),
            OUTCOME_MISSING, market=market, require_ip=require_ip,
            base_url=base_url, profile=profile)
    else:
        key, secret = resolved.require()
        redactor.register(key.reveal())
        redactor.register(secret.reveal())
        report = check_permissions(key.reveal(), secret.reveal(),
                                   transport=transport, market=market,
                                   require_ip=require_ip, base_url=base_url,
                                   profile=profile)
    _emit(report, json_mode=bool(getattr(args, "json", False)),
          redactor=redactor)
    return report.exit_code


def cmd_keys_check(args: argparse.Namespace) -> int:
    """Pre-trade permission check. Read-only: one signed GET."""
    return run_check(args)
