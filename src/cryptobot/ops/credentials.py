"""Secret storage for the live venue keys. Nothing here echoes a value.

Rules this module exists to keep (trade-ready release):

* a secret never reaches stdout, stderr, a log line, a JSON document, an
  exception message or git history;
* the backend is the macOS Keychain (``security`` CLI) on darwin, and a
  git-ignored dotenv file written mode 0600 everywhere else;
* writing a secret to a path git tracks, or to a path git does not ignore,
  is a hard refusal (``UnsafeSecretPath``);
* the trading process resolves a name in this order: real environment
  variable, then Keychain, then dotenv;
* a status call reports presence and backend as booleans/names only - never
  a value, a prefix or a suffix.

Store shapes are deliberately small so they can be injected in tests: the
Keychain store takes a subprocess runner, the dotenv store takes a git
runner, and nothing in this module opens a socket.

Known limitation: ``security add-generic-password`` accepts the secret only
as an argv word, so it is briefly visible in the process table to the same
user. macOS offers no stdin channel for it. Every other path (prompt, stdin,
dotenv, reading back) never puts a value on a command line.
"""
from __future__ import annotations

import getpass
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

# Two profiles, deliberately disjoint: a production key can never satisfy a
# demo run and a demo key can never satisfy a capital-bearing one.
PROFILE_PROD = "prod"
PROFILE_DEMO = "demo"
PROFILES: tuple[str, str] = (PROFILE_PROD, PROFILE_DEMO)

API_KEY_ENV = "CRYPTOBOT_API_KEY"
API_SECRET_ENV = "CRYPTOBOT_API_SECRET"
DEMO_KEY_ENV = "CRYPTOBOT_DEMO_KEY"
DEMO_SECRET_ENV = "CRYPTOBOT_DEMO_SECRET"

PROFILE_NAMES: dict[str, tuple[str, str]] = {
    PROFILE_PROD: (API_KEY_ENV, API_SECRET_ENV),
    PROFILE_DEMO: (DEMO_KEY_ENV, DEMO_SECRET_ENV),
}
SECRET_ENV_NAMES: tuple[str, ...] = (
    API_KEY_ENV, API_SECRET_ENV, DEMO_KEY_ENV, DEMO_SECRET_ENV)

# Old names documented for the demo drill. Accepted as an environment-only
# fallback for the demo profile so nothing already written breaks, and never
# consulted for the prod profile.
LEGACY_DEMO_ENV: dict[str, str] = {
    DEMO_KEY_ENV: "BINANCE_DEMO_KEY",
    DEMO_SECRET_ENV: "BINANCE_DEMO_SECRET",
}

KEYCHAIN_SERVICE = "cryptobot"
DEFAULT_ENV_PATH = ".env"
DEFAULT_DOTENV_MODE = 0o600
REDACTED = "<redacted>"

BACKEND_KEYCHAIN = "keychain"
BACKEND_DOTENV = "dotenv"
BACKENDS: tuple[str, str] = (BACKEND_KEYCHAIN, BACKEND_DOTENV)

SOURCE_ENVIRONMENT = "environment"
SOURCE_ENVIRONMENT_LEGACY = "environment-legacy"
SOURCE_KEYCHAIN = "keychain"
SOURCE_DOTENV = "dotenv"
SOURCE_MISSING = "missing"

# Binance issues 64-character alphanumeric keys and secrets. The key is
# accepted a little wider so a longer key is not rejected outright; the
# secret is exact because it is the HMAC-SHA256 key every signed call uses.
API_KEY_MIN_LEN = 32
API_KEY_MAX_LEN = 128
API_SECRET_LEN = 64
_ALNUM_RE = re.compile(r"\A[A-Za-z0-9]+\Z")
_WHITESPACE_RE = re.compile(r"\s")

# Values people paste from a template. Kept narrow on purpose: a real key is
# random base64-ish text, so these substrings never appear in one.
_PLACEHOLDERS = frozenset({
    "changeme", "change-me", "change_me", "replaceme", "replace-me",
    "placeholder", "yourkey", "your-key", "yoursecret", "your-secret",
    "dummy", "testing", "apikey", "apisecret", "undefined", "none", "null",
})
_PLACEHOLDER_HINTS = (
    "changeme", "change-me", "your", "placeholder", "example", "dummy",
    "redacted", "insert", "replace", "xxxx", "abcabc", "123456",
)

# Field names whose values must never survive redaction.
_SECRET_FIELD_RE = re.compile(
    r"(?i)(?P<name>\b(?:api[_-]?key|api[_-]?secret|apikey|apisecret|secret"
    r"|password|passwd|token|signature))"
    r"(?:[\"']?\s*[=:]\s*)(?P<q>[\"']?)"
    r"(?P<value>[^\s\"',;{}\[\]]{4,})"
    r"(?P=q)"
)
# A signed query string (``...&signature=<hex>``) carries no key material but
# is worth scrubbing from a journalled request line.
_SIGNED_QUERY_RE = re.compile(r"(?i)\bsignature=[0-9a-f]{8,}")


class CredentialError(RuntimeError):
    """Base class. Messages must never contain a secret value."""


class CredentialFormatError(CredentialError, ValueError):
    """A supplied value does not look like a venue API key/secret."""


class UnsafeSecretPath(CredentialError):
    """Refused: the target is tracked by git, or is not git-ignored."""


class MissingCredentials(CredentialError):
    """A required credential is present in no backend."""

    def __init__(self, names: Sequence[str]) -> None:
        self.names = tuple(names)
        super().__init__("missing credential(s): " + ", ".join(self.names))


class SecretStoreError(CredentialError):
    """A backend refused to store or read a value."""


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
def redact(value: object) -> str:
    """Return a display form of one value: empty, or the marker."""
    if value is None:
        return ""
    return REDACTED if str(value) else ""


class Redactor:
    """Scrub known secrets and secret-shaped fields out of any text/document.

    Used on every line this module prints and on the structured payloads the
    CLI emits, so a stray value cannot reach a terminal or a JSON document.
    """

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        self._secrets: list[str] = []
        for value in secrets:
            self.register(value)

    def register(self, value: str | None) -> None:
        """Remember one literal to scrub (no-op for empty values)."""
        if not value:
            return
        if value not in self._secrets:
            self._secrets.append(value)
            # Longest first: a secret that contains another must not leave
            # its tail behind after the shorter replacement.
            self._secrets.sort(key=len, reverse=True)

    def text(self, text: object) -> str:
        """Scrub one string."""
        out = "" if text is None else str(text)
        for value in self._secrets:
            out = out.replace(value, REDACTED)
        out = _SIGNED_QUERY_RE.sub(f"signature={REDACTED}", out)
        return _SECRET_FIELD_RE.sub(
            lambda m: f"{m.group('name')}={REDACTED}", out)

    def document(self, doc: Any) -> Any:
        """Scrub a JSON-shaped document (dict/list/scalar) recursively."""
        if isinstance(doc, Mapping):
            clean: dict[Any, Any] = {}
            for key, value in doc.items():
                if isinstance(key, str) and _is_secret_field(key):
                    clean[key] = REDACTED if value not in (None, "") else ""
                else:
                    clean[key] = self.document(value)
            return clean
        if isinstance(doc, (list, tuple)):
            return [self.document(item) for item in doc]
        if isinstance(doc, str):
            return self.text(doc)
        return doc

    def lines(self, lines: Iterable[object]) -> list[str]:
        return [self.text(line) for line in lines]


def _is_secret_field(name: str) -> bool:
    lowered = name.lower().replace("-", "_")
    return lowered in {
        "api_key", "api_secret", "apikey", "apisecret", "secret",
        "key", "token", "password", "passwd", "signature",
    } or "secret" in lowered


def redact_text(text: object, secrets: Iterable[str] = ()) -> str:
    """Convenience: scrub one string with the given literals."""
    return Redactor(secrets).text(text)


def redact_document(doc: Any, secrets: Iterable[str] = ()) -> Any:
    """Convenience: scrub a JSON-shaped document."""
    return Redactor(secrets).document(doc)


class RedactionFilter(logging.Filter):
    """Logging filter that scrubs registered secrets from every record."""

    def __init__(self, redactor: Redactor, name: str = "") -> None:
        super().__init__(name)
        self.redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.redactor.text(record.msg)
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = {k: self.redactor.text(v)
                               for k, v in record.args.items()}
            else:
                record.args = tuple(self.redactor.text(a)
                                    for a in record.args)
        return True


# ---------------------------------------------------------------------------
# A secret that cannot be printed by accident
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Secret:
    """One resolved secret. ``repr``/``str``/``format`` never show a value."""

    name: str
    value: str = field(repr=False, default="")

    def reveal(self) -> str:
        """The value, for the one place that signs a request."""
        return self.value

    def __str__(self) -> str:
        return f"<secret {self.name} {'set' if self.value else 'unset'}>"

    def __format__(self, spec: str) -> str:
        return str(self)

    def __bool__(self) -> bool:
        return bool(self.value)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def profile_names(profile: str) -> tuple[str, str]:
    """The (key, secret) environment names one profile uses."""
    try:
        return PROFILE_NAMES[profile]
    except KeyError:
        raise CredentialFormatError(
            f"unknown profile {profile!r} (want one of {PROFILES})") from None


def _expected_shape(name: str) -> str:
    if name in (API_SECRET_ENV, DEMO_SECRET_ENV):
        return f"{API_SECRET_LEN} alphanumeric characters"
    return (f"{API_KEY_MIN_LEN}-{API_KEY_MAX_LEN} alphanumeric characters "
            f"(Binance issues {API_SECRET_LEN})")


def is_placeholder(value: str) -> bool:
    """True when a value looks copied from a template rather than issued."""
    lowered = value.strip().lower()
    if not lowered:
        return True
    if lowered in _PLACEHOLDERS:
        return True
    if len(set(lowered)) == 1:
        return True
    return any(hint in lowered for hint in _PLACEHOLDER_HINTS)


def validate_secret(name: str, value: str | None) -> str:
    """Return the value when it has a plausible shape, else raise.

    The raised message names the credential and the expected shape only: it
    never repeats the value, its prefix or its suffix.
    """
    if name not in SECRET_ENV_NAMES:
        raise CredentialFormatError(f"unknown credential name {name!r}")
    if not value:
        raise CredentialFormatError(f"{name} is empty; expected "
                                   f"{_expected_shape(name)}")
    candidate = value.strip()
    if _WHITESPACE_RE.search(candidate):
        raise CredentialFormatError(
            f"{name} contains whitespace; paste the value on its own; "
            f"expected {_expected_shape(name)}")
    if not _ALNUM_RE.match(candidate):
        raise CredentialFormatError(
            f"{name} must be alphanumeric only; expected "
            f"{_expected_shape(name)}")
    if is_placeholder(candidate):
        raise CredentialFormatError(
            f"{name} looks like a placeholder, not a value issued by the "
            f"venue; expected {_expected_shape(name)}")
    if name in (API_SECRET_ENV, DEMO_SECRET_ENV):
        if len(candidate) != API_SECRET_LEN:
            raise CredentialFormatError(
                f"{name} has the wrong length; want exactly "
                f"{API_SECRET_LEN} alphanumeric characters")
    elif not API_KEY_MIN_LEN <= len(candidate) <= API_KEY_MAX_LEN:
        raise CredentialFormatError(
            f"{name} has the wrong length; want {_expected_shape(name)}")
    return candidate


def validate_pair(pairs: Mapping[str, str]) -> dict[str, str]:
    """Validate every supplied credential before anything is written."""
    return {name: validate_secret(name, value)
            for name, value in pairs.items()}


# ---------------------------------------------------------------------------
# git path safety
# ---------------------------------------------------------------------------
GitRunner = Callable[[Sequence[str], Path], tuple[int, str, str]]


def _run_git(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(["git", *argv], cwd=str(cwd),
                              capture_output=True, text=True, check=False,
                              timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 128, "", "git unavailable"
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


@dataclass(frozen=True)
class PathSafety:
    """What git says about one target path."""

    path: Path
    inside_repo: bool
    tracked: bool
    ignored: bool

    @property
    def safe(self) -> bool:
        """A secret may be written only here."""
        if self.tracked:
            return False
        return self.ignored or not self.inside_repo

    def describe(self) -> str:
        if not self.inside_repo:
            return f"{self.path}: outside any git work tree"
        state = "tracked" if self.tracked else "untracked"
        ignore = "ignored" if self.ignored else "NOT ignored"
        return f"{self.path}: {state}, {ignore} by git"


def inspect_secret_path(path: Path | str, *,
                        runner: GitRunner = _run_git) -> PathSafety:
    """Ask git whether this path may hold a secret. Read-only."""
    target = Path(path).expanduser().resolve()
    probe = target if target.is_dir() else target.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    code, out, _ = runner(["rev-parse", "--show-toplevel"], probe)
    if code != 0 or not out:
        return PathSafety(target, inside_repo=False, tracked=False,
                          ignored=False)
    toplevel = Path(out).resolve()
    try:
        rel = target.relative_to(toplevel)
    except ValueError:
        return PathSafety(target, inside_repo=False, tracked=False,
                          ignored=False)
    rel_text = rel.as_posix()
    tracked_code, _, _ = runner(["ls-files", "--error-unmatch", "--", rel_text],
                                toplevel)
    ignore_code, _, _ = runner(["check-ignore", "-q", "--", rel_text], toplevel)
    return PathSafety(target, inside_repo=True,
                      tracked=tracked_code == 0,
                      ignored=ignore_code == 0)


def require_safe_secret_path(path: Path | str, *,
                             runner: GitRunner = _run_git) -> PathSafety:
    """Hard refusal: never write a secret to a tracked or unignored path."""
    safety = inspect_secret_path(path, runner=runner)
    if safety.tracked:
        raise UnsafeSecretPath(
            f"refusing to write {safety.path}: git tracks this file, and a "
            f"secret must never enter git history (choose an ignored path, "
            f"or run `cryptobot keys set --backend keychain`)")
    if safety.inside_repo and not safety.ignored:
        raise UnsafeSecretPath(
            f"refusing to write {safety.path}: git does not ignore this "
            f"path, so the value could be committed (add it to .gitignore "
            f"first)")
    return safety


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
SubprocessRunner = Callable[[Sequence[str]], tuple[int, str, str]]


def _run_subprocess(argv: Sequence[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(list(argv), capture_output=True, text=True,
                              check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 127, "", "command failed"
    return proc.returncode, proc.stdout, proc.stderr


class SecretStore:
    """Common surface: presence, read, write. Never prints a value."""

    name = ""

    def available(self) -> bool:  # pragma: no cover - overridden
        return False

    def get(self, name: str) -> str | None:  # pragma: no cover - overridden
        raise NotImplementedError

    def set(self, name: str, value: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def has(self, name: str) -> bool:
        return self.get(name) is not None


class KeychainStore(SecretStore):
    """macOS Keychain entry via ``security`` (service ``cryptobot``)."""

    name = BACKEND_KEYCHAIN

    def __init__(self, service: str = KEYCHAIN_SERVICE, *,
                 runner: SubprocessRunner = _run_subprocess,
                 platform: str | None = None,
                 which: Callable[[str], str | None] = shutil.which) -> None:
        self._service = service
        self._runner = runner
        self._platform = platform
        self._which = which

    def available(self) -> bool:
        platform = self._platform if self._platform is not None else sys.platform
        return platform == "darwin" and bool(self._which("security"))

    def get(self, name: str) -> str | None:
        if not self.available():
            return None
        code, out, _ = self._runner(
            ["security", "find-generic-password", "-s", self._service,
             "-a", name, "-w"])
        if code != 0:
            return None
        value = out.strip()
        return value or None

    def set(self, name: str, value: str) -> None:
        if not self.available():
            raise SecretStoreError(
                f"the {BACKEND_KEYCHAIN} backend needs macOS and the "
                f"`security` CLI; use --backend {BACKEND_DOTENV} here")
        validated = validate_secret(name, value)
        code, _, _ = self._runner(
            ["security", "add-generic-password", "-U", "-s", self._service,
             "-a", name, "-w", validated])
        if code != 0:
            # Exit code only: security's own stderr is not echoed back.
            raise SecretStoreError(
                f"the keychain refused to store {name} (security exit "
                f"{code})")

    def delete(self, name: str) -> bool:
        if not self.available():
            return False
        code, _, _ = self._runner(
            ["security", "delete-generic-password", "-s", self._service,
             "-a", name])
        return code == 0


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].lstrip()
    if "=" not in stripped:
        return None
    name, _, raw = stripped.partition("=")
    name = name.strip()
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if not name:
        return None
    return name, value


class DotenvStore(SecretStore):
    """Git-ignored dotenv file, written mode 0600."""

    name = BACKEND_DOTENV

    def __init__(self, path: Path | str = DEFAULT_ENV_PATH, *,
                 git_runner: GitRunner = _run_git,
                 mode: int = DEFAULT_DOTENV_MODE) -> None:
        self._path = Path(path).expanduser()
        self._git_runner = git_runner
        self._mode = mode

    @property
    def path(self) -> Path:
        return self._path

    def available(self) -> bool:
        return True

    def safety(self) -> PathSafety:
        return inspect_secret_path(self._path, runner=self._git_runner)

    def get(self, name: str) -> str | None:
        for parsed in self._entries():
            if parsed[0] == name:
                return parsed[1] or None
        return None

    def _entries(self) -> list[tuple[str, str]]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return []
        entries = []
        for line in text.splitlines():
            parsed = _parse_dotenv_line(line)
            if parsed is not None:
                entries.append(parsed)
        return entries

    def set(self, name: str, value: str) -> None:
        validated = validate_secret(name, value)
        require_safe_secret_path(self._path, runner=self._git_runner)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        replaced = False
        try:
            existing = self._path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
        for line in existing.splitlines():
            parsed = _parse_dotenv_line(line)
            if parsed is not None and parsed[0] == name:
                if not replaced:
                    lines.append(f"{name}={validated}")
                    replaced = True
                continue
            lines.append(line)
        if not replaced:
            lines.append(f"{name}={validated}")
        payload = "\n".join(lines).rstrip("\n") + "\n"
        self._write_private(payload)

    def _write_private(self, payload: str) -> None:
        """Temp file in the same directory, 0600, then atomic rename."""
        handle, tmp_name = tempfile.mkstemp(
            dir=str(self._path.parent), prefix=f".{self._path.name}.",
            suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp_name, self._mode)
            os.replace(tmp_name, self._path)
        except BaseException:
            with suppress(OSError):
                os.unlink(tmp_name)
            raise
        with suppress(OSError):
            os.chmod(self._path, self._mode)

    def mode(self) -> int | None:
        try:
            return self._path.stat().st_mode & 0o777
        except OSError:
            return None


def default_backend(*, keychain: KeychainStore | None = None) -> str:
    """Keychain on macOS, dotenv everywhere else."""
    store = keychain if keychain is not None else KeychainStore()
    return BACKEND_KEYCHAIN if store.available() else BACKEND_DOTENV


def make_store(backend: str | None = None, *, env_path: Path | str | None = None,
               keychain: KeychainStore | None = None,
               dotenv: DotenvStore | None = None) -> SecretStore:
    """Build the requested backend store (default: platform default)."""
    chosen = backend or default_backend(keychain=keychain)
    if chosen == BACKEND_KEYCHAIN:
        return keychain if keychain is not None else KeychainStore()
    if chosen == BACKEND_DOTENV:
        if dotenv is not None:
            return dotenv
        return DotenvStore(env_path or DEFAULT_ENV_PATH)
    raise SecretStoreError(f"unknown credential backend {chosen!r}")


# ---------------------------------------------------------------------------
# Resolution: environment -> Keychain -> dotenv
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SecretSource:
    """Presence and origin of one credential. No value, prefix or suffix."""

    name: str
    present: bool
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "present": self.present,
                "source": self.source}


@dataclass(frozen=True)
class ProfileStatus:
    """Presence of one profile's key and secret. No value, prefix or suffix."""

    profile: str
    sources: tuple[SecretSource, ...]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.sources)

    @property
    def complete(self) -> bool:
        return all(entry.present for entry in self.sources)

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(e.name for e in self.sources if not e.present)

    def as_dict(self) -> dict[str, Any]:
        return {"profile": self.profile, "complete": self.complete,
                "missing": list(self.missing),
                "credentials": [e.as_dict() for e in self.sources]}


@dataclass(frozen=True)
class CredentialStatus:
    """What `cryptobot keys status` reports."""

    backend: str
    dotenv_path: Path
    dotenv_safety: PathSafety
    profiles: tuple[ProfileStatus, ...]
    profile: str = PROFILE_PROD
    dotenv_mode: int | None = None

    @property
    def selected(self) -> ProfileStatus:
        for entry in self.profiles:
            if entry.profile == self.profile:
                return entry
        raise CredentialFormatError(f"unknown profile {self.profile!r}")

    @property
    def sources(self) -> tuple[SecretSource, ...]:
        return self.selected.sources

    @property
    def complete(self) -> bool:
        """The selected profile is complete (status is per profile)."""
        return self.selected.complete

    @property
    def missing(self) -> tuple[str, ...]:
        return self.selected.missing

    @property
    def any_complete(self) -> bool:
        return any(entry.complete for entry in self.profiles)

    @property
    def holds_dotenv_secret(self) -> bool:
        return any(e.present and e.source in (SOURCE_DOTENV,)
                   for entry in self.profiles for e in entry.sources)

    @property
    def insecure(self) -> bool:
        """True when the dotenv backend holds a secret in a risky path."""
        if not self.holds_dotenv_secret:
            return False
        if not self.dotenv_safety.safe:
            return True
        return self.dotenv_mode is not None \
            and self.dotenv_mode != DEFAULT_DOTENV_MODE

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "profile": self.profile,
            "dotenv_path": str(self.dotenv_path),
            "dotenv_ignored": bool(self.dotenv_safety.ignored),
            "dotenv_tracked": bool(self.dotenv_safety.tracked),
            "dotenv_inside_repo": bool(self.dotenv_safety.inside_repo),
            "dotenv_mode": (None if self.dotenv_mode is None
                            else oct(self.dotenv_mode)),
            "dotenv_insecure": self.insecure,
            "complete": self.complete,
            "missing": list(self.missing),
            "credentials": [e.as_dict() for e in self.sources],
            "profiles": {entry.profile: entry.as_dict()
                         for entry in self.profiles},
        }


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def resolve(name: str, *, environ: Mapping[str, str] | None = None,
            dotenv: DotenvStore | None = None,
            keychain: KeychainStore | None = None,
            legacy_env: Sequence[str] = (),
            ) -> tuple[str | None, str]:
    """Resolve one name in process order: env, then Keychain, then dotenv.

    ``legacy_env`` names an older environment variable accepted for this
    profile only (the demo profile's documented BINANCE_DEMO_* pair). It is
    read after the canonical name and before any store, and never for prod.
    """
    env = os.environ if environ is None else environ
    value = _clean(env.get(name))
    if value:
        return value, SOURCE_ENVIRONMENT
    for alias in legacy_env:
        value = _clean(env.get(alias))
        if value:
            return value, SOURCE_ENVIRONMENT_LEGACY
    if keychain is not None and keychain.available():
        value = _clean(keychain.get(name))
        if value:
            return value, SOURCE_KEYCHAIN
    if dotenv is not None:
        value = _clean(dotenv.get(name))
        if value:
            return value, SOURCE_DOTENV
    return None, SOURCE_MISSING


def _legacy_for(profile: str, name: str) -> tuple[str, ...]:
    if profile != PROFILE_DEMO:
        return ()
    alias = LEGACY_DEMO_ENV.get(name)
    return (alias,) if alias else ()


def describe_sources(*, profile: str = PROFILE_PROD,
                     environ: Mapping[str, str] | None = None,
                     dotenv: DotenvStore | None = None,
                     keychain: KeychainStore | None = None,
                     ) -> tuple[SecretSource, ...]:
    """Presence/backend for one profile, never a value."""
    out = []
    for name in profile_names(profile):
        value, source = resolve(name, environ=environ, dotenv=dotenv,
                                keychain=keychain,
                                legacy_env=_legacy_for(profile, name))
        out.append(SecretSource(name, value is not None, source))
    return tuple(out)


def status(*, env_path: Path | str | None = None,
           environ: Mapping[str, str] | None = None,
           keychain: KeychainStore | None = None,
           backend: str | None = None,
           profile: str = PROFILE_PROD) -> CredentialStatus:
    """Report which credentials exist, where, and whether that is safe.

    Both profiles are always reported; ``profile`` picks the one the exit
    verdict (complete / missing) refers to.
    """
    profile_names(profile)  # validate early
    keychain_store = keychain if keychain is not None else KeychainStore()
    dotenv = DotenvStore(env_path or DEFAULT_ENV_PATH)
    return CredentialStatus(
        backend=backend or default_backend(keychain=keychain_store),
        dotenv_path=dotenv.path,
        dotenv_safety=dotenv.safety(),
        profiles=tuple(
            ProfileStatus(name, describe_sources(
                profile=name, environ=environ, dotenv=dotenv,
                keychain=keychain_store))
            for name in PROFILES),
        profile=profile,
        dotenv_mode=dotenv.mode(),
    )


@dataclass(frozen=True)
class Credentials:
    """Resolved credentials for one profile."""

    sources: tuple[SecretSource, ...]
    secrets: Mapping[str, str] = field(repr=False, default_factory=dict)
    profile: str = PROFILE_PROD

    @property
    def names(self) -> tuple[str, str]:
        return profile_names(self.profile)

    def get(self, name: str) -> Secret | None:
        value = self.secrets.get(name)
        if not value:
            return None
        return Secret(name, value)

    @property
    def key_name(self) -> str:
        return self.names[0]

    @property
    def secret_name(self) -> str:
        return self.names[1]

    @property
    def api_key(self) -> Secret | None:
        """The profile's key (prod by default, demo for the demo profile)."""
        return self.get(self.key_name)

    @property
    def api_secret(self) -> Secret | None:
        return self.get(self.secret_name)

    @property
    def complete(self) -> bool:
        return all(entry.present for entry in self.sources)

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(e.name for e in self.sources if not e.present)

    def require(self) -> tuple[Secret, Secret]:
        """Both credentials for this profile, or raise naming what is missing."""
        if self.missing:
            raise MissingCredentials(self.missing)
        key, secret = self.get(self.key_name), self.get(self.secret_name)
        assert key is not None and secret is not None
        return key, secret

    def __repr__(self) -> str:
        present = ", ".join(f"{e.name}={e.source}" for e in self.sources)
        return f"Credentials(profile={self.profile}, {present})"


def load_credentials(*, profile: str = PROFILE_PROD,
                     environ: Mapping[str, str] | None = None,
                     env_path: Path | str | None = None,
                     keychain: KeychainStore | None = None) -> Credentials:
    """The trading-process load order: env, Keychain, dotenv.

    Names come from the profile only: a prod key never satisfies the demo
    profile and a demo key never satisfies prod.
    """
    keychain_store = keychain if keychain is not None else KeychainStore()
    dotenv = DotenvStore(env_path or DEFAULT_ENV_PATH)
    resolved: dict[str, str] = {}
    sources: list[SecretSource] = []
    for name in profile_names(profile):
        value, source = resolve(name, environ=environ, dotenv=dotenv,
                                keychain=keychain_store,
                                legacy_env=_legacy_for(profile, name))
        sources.append(SecretSource(name, value is not None, source))
        if value is not None:
            resolved[name] = value
    return Credentials(tuple(sources), resolved, profile)


# ---------------------------------------------------------------------------
# Interactive / piped entry
# ---------------------------------------------------------------------------
DEFAULT_OVERWRITE_PROMPT = "{name} is already stored ({backend}). Overwrite? [y/N] "


@dataclass(frozen=True)
class EntryResult:
    """Outcome of one credential entry. Never carries the value."""

    name: str
    written: bool
    note: str = ""


def collect_entries(store: SecretStore, *,
                    from_stdin: bool = False,
                    stdin: TextIO | None = None,
                    getpass_fn: Callable[[str], str] = getpass.getpass,
                    prompt_fn: Callable[[str], str] = input,
                    force: bool = False,
                    profile: str = PROFILE_PROD,
                    names: Sequence[str] | None = None,
                    ) -> tuple[dict[str, str], list[EntryResult]]:
    """Read credentials without echo and validate them; write nothing yet.

    Interactive reads use ``getpass`` so the terminal never shows the value;
    ``from_stdin`` reads one value per line for piping. An existing entry is
    only replaced after a confirmation, unless ``force`` is set.
    """
    wanted = tuple(names) if names is not None else profile_names(profile)
    gathered: dict[str, str] = {}
    results: list[EntryResult] = []
    if from_stdin:
        stream = stdin if stdin is not None else sys.stdin
        for name in wanted:
            line = stream.readline()
            if not line:
                raise CredentialFormatError(
                    f"--from-stdin needs {len(wanted)} lines: "
                    f"{', '.join(wanted)} (one value per line, in that "
                    f"order); no value is echoed")
            gathered[name] = validate_secret(name, line)
        return gathered, [EntryResult(n, True, "read from stdin")
                          for n in wanted]
    for name in wanted:
        if store.has(name) and not force:
            answer = prompt_fn(DEFAULT_OVERWRITE_PROMPT.format(
                name=name, backend=store.name))
            if answer.strip().lower() not in ("y", "yes"):
                results.append(EntryResult(name, False, "kept existing entry"))
                continue
        value = getpass_fn(f"{name} (input hidden): ")
        gathered[name] = validate_secret(name, value)
        results.append(EntryResult(name, True, "validated"))
    return gathered, results


def write_credentials(store: SecretStore, values: Mapping[str, str],
                      *,
                      profile: str | None = None) -> list[EntryResult]:
    """Validate everything, then write each value to the store."""
    validated = validate_pair(values)
    names = tuple(values) if profile is None else profile_names(profile)
    results = []
    for name in names:
        if name not in validated:
            continue
        store.set(name, validated[name])
        results.append(EntryResult(name, True,
                                   f"stored in {store.name}"))
    return results
