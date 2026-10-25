"""`cryptobot keys` storage: redaction, backends, git safety, load order.

Everything here is offline: the Keychain store takes an injected runner, the
dotenv store takes an injected git runner (real git is used in the git-safety
tests, in a throwaway repository), and no test opens a socket.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from cryptobot.ops import credentials as cred

# Sentinel values: 32/64 alphanumeric characters that carry a recognisable
# substring, so "the value leaked" is an unambiguous assertion.
API_KEY = ("K3yS3nt1nel" * 6)[:32]
API_SECRET = ("S3cretS3nt1nel" * 6)[:64]
KEY_PREFIX, KEY_SUFFIX = API_KEY[:8], API_KEY[-8:]
SECRET_PREFIX, SECRET_SUFFIX = API_SECRET[:8], API_SECRET[-8:]


def _git(*argv: str, cwd: Path) -> None:
    subprocess.run(["git", *argv], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:  # pragma: no cover - git is a hard dep
        pytest.skip("git is required for the path-safety tests")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", str(repo), cwd=tmp_path)
    (repo / ".gitignore").write_text(".env\nignored/\n")
    _git("add", ".gitignore", cwd=repo)
    _git("-c", "user.email=t@example.test", "-c", "user.name=t",
         "commit", "-qm", "season 0", cwd=repo)
    return repo


class FakeRunner:
    """Stands in for the `security` CLI (or git) without running anything."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv, cwd=None):
        argv = list(argv)
        self.calls.append(argv)
        for needle, response in self.responses.items():
            if needle in argv:
                return response
        return (1, "", "not found")


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------
def test_redact_text_hides_registered_secret():
    text = f"pasted {API_KEY} and {API_SECRET} into the terminal"
    cleaned = cred.redact_text(text, [API_KEY, API_SECRET])
    assert API_KEY not in cleaned
    assert API_SECRET not in cleaned
    assert KEY_PREFIX not in cleaned
    assert SECRET_SUFFIX not in cleaned
    assert cred.REDACTED in cleaned


def test_redact_text_scrubs_unregistered_secret_values():
    # Nothing registered: only the shape of the field can save this line.
    stranger = "Q9w8E7r6T5y4U3i2O1p0A9s8D7f6G5h4"
    for line in (f"api_secret={stranger}",
                 f'{{"apiKey": "{stranger}"}}',
                 f"password: {stranger}",
                 f"GET /sapi/v1/x?timestamp=1&signature={stranger}"):
        cleaned = cred.redact_text(line)
        assert stranger not in cleaned, line
        assert cred.REDACTED in cleaned, line


def test_redact_text_scrubs_secret_shaped_fields():
    for line in (f"api_secret={API_SECRET}",
                 f'{{"apiKey": "{API_KEY}"}}',
                 f"X-MBX-APIKEY: {API_KEY}",
                 f"GET /sapi/v1/x?timestamp=1&signature={API_SECRET}"):
        cleaned = cred.redact_text(line, [API_KEY, API_SECRET])
        assert API_KEY not in cleaned, line
        assert API_SECRET not in cleaned, line


def test_redact_document_scrubs_nested_json():
    document = {
        "status": 200,
        "request": {"X-MBX-APIKEY": API_KEY,
                    "query": f"timestamp=1&signature={API_SECRET}"},
        "note": f"used {API_SECRET}",
        "nested": [{"apiSecret": API_SECRET}],
    }
    payload = json.dumps(cred.redact_document(document, [API_KEY, API_SECRET]))
    assert API_KEY not in payload
    assert API_SECRET not in payload
    assert KEY_PREFIX not in payload
    assert SECRET_SUFFIX not in payload


def test_redact_document_redacts_secret_named_keys():
    document = {"api_key": API_KEY, "api_secret": API_SECRET,
                "enableReading": True}
    cleaned = cred.redact_document(document)
    assert cleaned["api_key"] == cred.REDACTED
    assert cleaned["api_secret"] == cred.REDACTED
    assert cleaned["enableReading"] is True


def test_redaction_filter_removes_secret_from_log_records():
    redactor = cred.Redactor([API_KEY, API_SECRET])
    record = logging.LogRecord(
        name="cryptobot", level=logging.INFO, pathname=__file__, lineno=1,
        msg="key %s secret %s", args=(API_KEY, API_SECRET), exc_info=None)
    assert cred.RedactionFilter(redactor).filter(record) is True
    rendered = record.getMessage()
    assert API_KEY not in rendered
    assert API_SECRET not in rendered


def test_secret_never_prints_its_value():
    secret = cred.Secret(cred.API_SECRET_ENV, API_SECRET)
    assert secret.reveal() == API_SECRET
    for rendered in (str(secret), repr(secret), f"{secret}", str(secret)):
        assert API_SECRET not in rendered
    assert API_SECRET not in repr(cred.Credentials(
        (cred.SecretSource(cred.API_SECRET_ENV, True, cred.SOURCE_DOTENV),),
        {cred.API_SECRET_ENV: API_SECRET}))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_validate_accepts_the_issued_shape():
    assert cred.validate_secret(cred.API_KEY_ENV, API_KEY) == API_KEY
    assert cred.validate_secret(cred.API_SECRET_ENV, API_SECRET) == API_SECRET
    # A pasted trailing newline (stdin) is tolerated, not echoed.
    assert cred.validate_secret(cred.API_SECRET_ENV,
                                API_SECRET + "\n") == API_SECRET


@pytest.mark.parametrize("value", [
    f"{API_KEY} {API_SECRET}",      # internal whitespace
    f"{API_KEY}\t\tabc",
    "not-alphanumeric!" + "a" * 50,
    "your_api_key_here" + "a" * 50,
    "changeme" + "a" * 50,
    "a" * 64,                       # one repeated character
])
def test_validate_rejects_bad_shapes_without_echoing(value):
    with pytest.raises(cred.CredentialFormatError) as excinfo:
        cred.validate_secret(cred.API_KEY_ENV, value)
    assert value not in str(excinfo.value)
    assert value.strip()[:6] not in str(excinfo.value)


def test_validate_rejects_wrong_lengths():
    with pytest.raises(cred.CredentialFormatError):
        cred.validate_secret(cred.API_SECRET_ENV, API_KEY)  # 32, needs 64
    with pytest.raises(cred.CredentialFormatError):
        cred.validate_secret(cred.API_KEY_ENV, "ab")
    with pytest.raises(cred.CredentialFormatError):
        cred.validate_secret(cred.API_KEY_ENV, "")
    with pytest.raises(cred.CredentialFormatError):
        cred.validate_secret("SOME_OTHER_NAME", API_KEY)


def test_validate_pair_rejects_before_any_write():
    with pytest.raises(cred.CredentialFormatError):
        cred.validate_pair({cred.API_KEY_ENV: API_KEY,
                            cred.API_SECRET_ENV: "short"})


# ---------------------------------------------------------------------------
# dotenv backend
# ---------------------------------------------------------------------------
def test_dotenv_write_is_0600_and_round_trips(tmp_path: Path):
    store = cred.DotenvStore(tmp_path / ".env")
    store.set(cred.API_KEY_ENV, API_KEY)
    store.set(cred.API_SECRET_ENV, API_SECRET)
    assert store.mode() == 0o600
    assert store.get(cred.API_KEY_ENV) == API_KEY
    assert store.get(cred.API_SECRET_ENV) == API_SECRET
    assert not list(tmp_path.glob("*.tmp"))  # no temp file left behind


def test_dotenv_update_keeps_other_lines(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("# keep me\nexport OTHER=1\n"
                    f"{cred.API_KEY_ENV}=old\n")
    store = cred.DotenvStore(path)
    store.set(cred.API_KEY_ENV, API_KEY)
    text = path.read_text()
    assert "# keep me" in text
    assert "export OTHER=1" in text
    assert "old" not in text
    assert text.count(cred.API_KEY_ENV) == 1
    assert store.get(cred.API_KEY_ENV) == API_KEY


def test_dotenv_refuses_a_tracked_path(git_repo: Path):
    tracked = git_repo / "secrets.env"
    tracked.write_text("x=1\n")
    _git("add", "secrets.env", cwd=git_repo)
    safety = cred.inspect_secret_path(tracked)
    assert safety.tracked is True and safety.safe is False
    with pytest.raises(cred.UnsafeSecretPath) as excinfo:
        cred.DotenvStore(tracked).set(cred.API_KEY_ENV, API_KEY)
    assert "tracks this file" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)
    assert tracked.read_text() == "x=1\n"  # nothing written


def test_dotenv_refuses_a_path_git_does_not_ignore(git_repo: Path):
    target = git_repo / "notes.txt"
    safety = cred.inspect_secret_path(target)
    assert safety.inside_repo is True
    assert safety.ignored is False and safety.safe is False
    with pytest.raises(cred.UnsafeSecretPath) as excinfo:
        cred.DotenvStore(target).set(cred.API_KEY_ENV, API_KEY)
    assert "does not ignore this path" in str(excinfo.value)
    assert not target.exists()


def test_dotenv_allows_an_ignored_path(git_repo: Path):
    target = git_repo / ".env"
    store = cred.DotenvStore(target)
    assert store.safety().ignored is True
    store.set(cred.API_KEY_ENV, API_KEY)
    assert store.get(cred.API_KEY_ENV) == API_KEY
    assert store.mode() == 0o600


# ---------------------------------------------------------------------------
# Keychain backend
# ---------------------------------------------------------------------------
def test_keychain_uses_service_and_account():
    runner = FakeRunner({
        "find-generic-password": (0, API_SECRET + "\n", ""),
        "add-generic-password": (0, "", ""),
    })
    store = cred.KeychainStore(runner=runner, platform="darwin",
                               which=lambda _name: "/usr/bin/security")
    assert store.available() is True
    assert store.get(cred.API_SECRET_ENV) == API_SECRET
    store.set(cred.API_SECRET_ENV, API_SECRET)
    find, add = runner.calls
    assert find[:3] == ["security", "find-generic-password", "-s"]
    assert cred.KEYCHAIN_SERVICE in find
    assert "-a" in find and cred.API_SECRET_ENV in find
    assert add[:3] == ["security", "add-generic-password", "-U"]
    assert cred.KEYCHAIN_SERVICE in add and cred.API_SECRET_ENV in add


def test_keychain_unavailable_off_darwin():
    store = cred.KeychainStore(platform="linux",
                               which=lambda _name: "/usr/bin/security")
    assert store.available() is False
    assert store.get(cred.API_KEY_ENV) is None
    with pytest.raises(cred.SecretStoreError):
        store.set(cred.API_KEY_ENV, API_KEY)


def test_keychain_refusal_does_not_echo_the_value():
    runner = FakeRunner({"add-generic-password": (44, "", "denied")})
    store = cred.KeychainStore(runner=runner, platform="darwin",
                               which=lambda _name: "/usr/bin/security")
    with pytest.raises(cred.SecretStoreError) as excinfo:
        store.set(cred.API_SECRET_ENV, API_SECRET)
    assert API_SECRET not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Load order: environment -> Keychain -> dotenv
# ---------------------------------------------------------------------------
def test_load_order_environment_then_keychain_then_dotenv():
    def keychain_runner(argv):
        if "find-generic-password" in argv:
            account = argv[argv.index("-a") + 1]
            if account == cred.API_KEY_ENV:
                return (0, "fromkeychain\n", "")
            return (44, "", "The specified item could not be found")
        return (0, "", "")

    keychain = cred.KeychainStore(runner=keychain_runner, platform="darwin",
                                  which=lambda _name: "/usr/bin/security")

    class DictDotenv(cred.DotenvStore):
        def __init__(self, values):
            super().__init__("/tmp/unused-for-load-order.env")
            self._values = values

        def get(self, name):
            return self._values.get(name)

    dotenv = DictDotenv({cred.API_KEY_ENV: "fromdotenv",
                         cred.API_SECRET_ENV: "fromdotenv"})
    # 1. the real environment wins over both backends
    value, source = cred.resolve(
        cred.API_KEY_ENV, environ={cred.API_KEY_ENV: "fromenv"},
        dotenv=dotenv, keychain=keychain)
    assert (value, source) == ("fromenv", cred.SOURCE_ENVIRONMENT)
    # 2. Keychain wins over dotenv
    value, source = cred.resolve(cred.API_KEY_ENV, environ={},
                                 dotenv=dotenv, keychain=keychain)
    assert (value, source) == ("fromkeychain", cred.SOURCE_KEYCHAIN)
    # 3. dotenv is the last resort
    value, source = cred.resolve(
        cred.API_SECRET_ENV, environ={}, dotenv=dotenv,
        keychain=cred.KeychainStore(platform="linux"))
    assert (value, source) == ("fromdotenv", cred.SOURCE_DOTENV)
    # 4. absent everywhere
    value, source = cred.resolve(
        "CRYPTOBOT_NOPE", environ={}, dotenv=dotenv, keychain=keychain)
    assert (value, source) == (None, cred.SOURCE_MISSING)


def test_an_empty_environment_variable_does_not_shadow_a_backend(tmp_path):
    path = tmp_path / ".env"
    cred.DotenvStore(path).set(cred.API_KEY_ENV, API_KEY)
    resolved = cred.load_credentials(environ={cred.API_KEY_ENV: "   "},
                                     env_path=path)
    assert resolved.api_key is not None
    assert resolved.api_key.reveal() == API_KEY
    assert [s.source for s in resolved.sources] == [cred.SOURCE_DOTENV,
                                                    cred.SOURCE_MISSING]


def test_status_reports_booleans_only(tmp_path):
    path = tmp_path / ".env"
    store = cred.DotenvStore(path)
    store.set(cred.API_KEY_ENV, API_KEY)
    store.set(cred.API_SECRET_ENV, API_SECRET)
    status = cred.status(env_path=path, environ={})
    payload = json.dumps(status.as_dict())
    for fragment in (API_KEY, API_SECRET, KEY_PREFIX, KEY_SUFFIX,
                     SECRET_PREFIX, SECRET_SUFFIX):
        assert fragment not in payload
    assert status.complete is True
    assert all(isinstance(e.present, bool) for e in status.sources)
    assert {e.source for e in status.sources} == {cred.SOURCE_DOTENV}
    assert status.insecure is False


def test_status_flags_missing_credentials(tmp_path: Path):
    status = cred.status(env_path=tmp_path / ".env", environ={})
    assert status.complete is False
    assert status.missing == (cred.API_KEY_ENV, cred.API_SECRET_ENV)
    assert status.holds_dotenv_secret is False
    assert status.insecure is False  # nothing is stored, so nothing is unsafe


def test_status_flags_a_world_readable_dotenv(tmp_path: Path):
    path = tmp_path / ".env"
    store = cred.DotenvStore(path)
    store.set(cred.API_KEY_ENV, API_KEY)
    store.set(cred.API_SECRET_ENV, API_SECRET)
    assert cred.status(env_path=path, environ={}).insecure is False
    path.chmod(0o644)
    loose = cred.status(env_path=path, environ={})
    assert loose.dotenv_mode == 0o644
    assert loose.insecure is True


def test_status_flags_an_unignored_dotenv(git_repo: Path):
    target = git_repo / "notes.txt"
    status = cred.CredentialStatus(
        backend=cred.BACKEND_DOTENV, dotenv_path=target,
        dotenv_safety=cred.inspect_secret_path(target),
        profiles=(cred.ProfileStatus(cred.PROFILE_PROD, (
            cred.SecretSource(cred.API_KEY_ENV, True, cred.SOURCE_DOTENV),
            cred.SecretSource(cred.API_SECRET_ENV, True,
                              cred.SOURCE_DOTENV))),),
        dotenv_mode=0o600)
    assert status.holds_dotenv_secret is True
    assert status.insecure is True
    assert status.as_dict()["dotenv_ignored"] is False


# ---------------------------------------------------------------------------
# Profiles: prod and demo never share a name
# ---------------------------------------------------------------------------
def test_profiles_use_disjoint_names():
    assert cred.PROFILE_NAMES[cred.PROFILE_PROD] == (cred.API_KEY_ENV,
                                                     cred.API_SECRET_ENV)
    assert cred.PROFILE_NAMES[cred.PROFILE_DEMO] == (cred.DEMO_KEY_ENV,
                                                     cred.DEMO_SECRET_ENV)
    assert not set(cred.PROFILE_NAMES[cred.PROFILE_PROD]) & set(
        cred.PROFILE_NAMES[cred.PROFILE_DEMO])
    with pytest.raises(cred.CredentialFormatError):
        cred.profile_names("live")


def test_prod_credentials_never_satisfy_the_demo_profile():
    prod_env = {cred.API_KEY_ENV: API_KEY, cred.API_SECRET_ENV: API_SECRET}
    demo = cred.load_credentials(profile=cred.PROFILE_DEMO, environ=prod_env)
    assert demo.complete is False
    assert demo.missing == (cred.DEMO_KEY_ENV, cred.DEMO_SECRET_ENV)
    with pytest.raises(cred.MissingCredentials) as excinfo:
        demo.require()
    assert cred.DEMO_KEY_ENV in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


def test_demo_credentials_never_satisfy_the_prod_profile():
    demo_env = {cred.DEMO_KEY_ENV: API_KEY, cred.DEMO_SECRET_ENV: API_SECRET}
    prod = cred.load_credentials(profile=cred.PROFILE_PROD, environ=demo_env)
    assert prod.complete is False


def test_demo_profile_accepts_the_legacy_environment_names():
    legacy = {"BINANCE_DEMO_KEY": API_KEY, "BINANCE_DEMO_SECRET": API_SECRET}
    demo = cred.load_credentials(profile=cred.PROFILE_DEMO, environ=legacy)
    assert demo.complete is True
    assert [s.source for s in demo.sources] == [
        cred.SOURCE_ENVIRONMENT_LEGACY, cred.SOURCE_ENVIRONMENT_LEGACY]
    key, secret = demo.require()
    assert key.reveal() == API_KEY and secret.reveal() == API_SECRET
    # The legacy names are a demo-only fallback: prod ignores them.
    assert cred.load_credentials(
        profile=cred.PROFILE_PROD, environ=legacy).complete is False


def test_demo_profile_prefers_its_canonical_name_over_the_legacy_one():
    environ = {cred.DEMO_KEY_ENV: API_KEY, "BINANCE_DEMO_KEY": "a" * 32,
               cred.DEMO_SECRET_ENV: API_SECRET}
    demo = cred.load_credentials(profile=cred.PROFILE_DEMO, environ=environ)
    assert demo.sources[0].source == cred.SOURCE_ENVIRONMENT
    assert demo.api_key.reveal() == API_KEY


def test_demo_profile_round_trips_through_the_dotenv_store(tmp_path):
    path = tmp_path / ".env"
    store = cred.DotenvStore(path)
    values, _ = cred.collect_entries(store, from_stdin=True,
                                     stdin=__import__("io").StringIO(
                                         f"{API_KEY}\n{API_SECRET}\n"),
                                     profile=cred.PROFILE_DEMO)
    cred.write_credentials(store, values, profile=cred.PROFILE_DEMO)
    assert store.get(cred.DEMO_KEY_ENV) == API_KEY
    assert store.get(cred.API_KEY_ENV) is None  # prod name untouched
    status = cred.status(env_path=path, environ={}, profile=cred.PROFILE_DEMO)
    assert status.complete is True
    assert status.profiles and {p.profile for p in status.profiles} == set(
        cred.PROFILES)


def test_demo_secret_has_the_same_shape_rule():
    with pytest.raises(cred.CredentialFormatError):
        cred.validate_secret(cred.DEMO_SECRET_ENV, API_KEY)  # 32, needs 64
    assert cred.validate_secret(cred.DEMO_SECRET_ENV, API_SECRET) == API_SECRET


def test_status_reports_both_profiles_separately(tmp_path):
    path = tmp_path / ".env"
    store = cred.DotenvStore(path)
    store.set(cred.API_KEY_ENV, API_KEY)
    store.set(cred.API_SECRET_ENV, API_SECRET)
    prod_status = cred.status(env_path=path, environ={})
    demo_status = cred.status(env_path=path, environ={},
                              profile=cred.PROFILE_DEMO)
    assert prod_status.complete is True
    assert demo_status.complete is False
    assert demo_status.missing == (cred.DEMO_KEY_ENV, cred.DEMO_SECRET_ENV)
    payload = json.dumps(demo_status.as_dict())
    assert "demo" in payload and "prod" in payload
    for fragment in (API_KEY, API_SECRET):
        assert fragment not in payload


# ---------------------------------------------------------------------------
# Interactive / piped entry
# ---------------------------------------------------------------------------
class MemoryStore(cred.SecretStore):
    name = cred.BACKEND_DOTENV

    def __init__(self, existing=None):
        self.values = dict(existing or {})

    def available(self):
        return True

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value


def test_interactive_entry_uses_getpass_and_validates():
    read: list[str] = []

    def fake_getpass(prompt):
        assert "hidden" in prompt
        read.append(prompt)
        return API_KEY if len(read) == 1 else API_SECRET

    store = MemoryStore()
    values, results = cred.collect_entries(store, getpass_fn=fake_getpass,
                                           prompt_fn=lambda _p: "n")
    assert values == {cred.API_KEY_ENV: API_KEY,
                      cred.API_SECRET_ENV: API_SECRET}
    assert all(result.written for result in results)
    assert len(read) == 2


def test_interactive_entry_asks_before_overwriting():
    store = MemoryStore({cred.API_KEY_ENV: API_KEY})
    prompts: list[str] = []
    values, results = cred.collect_entries(
        store, getpass_fn=lambda _p: API_SECRET,
        prompt_fn=lambda prompt: prompts.append(prompt) or "n")
    assert prompts and cred.API_KEY_ENV in prompts[0]
    assert cred.API_KEY_ENV not in values  # kept the existing entry
    assert cred.API_SECRET_ENV in values
    assert [r.written for r in results] == [False, True]


def test_interactive_entry_overwrites_when_confirmed():
    store = MemoryStore({cred.API_KEY_ENV: "old"})

    def fake_getpass(prompt):
        return API_SECRET if cred.API_SECRET_ENV in prompt else API_KEY

    values, _ = cred.collect_entries(
        store, getpass_fn=fake_getpass, prompt_fn=lambda _p: "yes")
    assert values[cred.API_KEY_ENV] == API_KEY
    assert values[cred.API_SECRET_ENV] == API_SECRET


def test_from_stdin_reads_two_lines_and_never_echoes(capsys):
    import io
    stream = io.StringIO(f"{API_KEY}\n{API_SECRET}\n")
    store = MemoryStore()
    values, results = cred.collect_entries(store, from_stdin=True, stdin=stream)
    written = cred.write_credentials(store, values)
    out = capsys.readouterr()
    assert API_KEY not in out.out + out.err
    assert API_SECRET not in out.out + out.err
    assert store.values[cred.API_SECRET_ENV] == API_SECRET
    assert len(results) == 2 and all(r.written for r in results)
    assert len(written) == 2


def test_from_stdin_with_a_missing_line_is_a_clear_refusal():
    import io
    with pytest.raises(cred.CredentialFormatError) as excinfo:
        cred.collect_entries(MemoryStore(), from_stdin=True,
                             stdin=io.StringIO(f"{API_KEY}\n"))
    assert "2 lines" in str(excinfo.value)
    assert "CRYPTOBOT_API_KEY" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


def test_write_credentials_validates_before_writing():
    store = MemoryStore()
    with pytest.raises(cred.CredentialFormatError):
        cred.write_credentials(store, {cred.API_KEY_ENV: API_KEY,
                                       cred.API_SECRET_ENV: "short"})
    assert store.values == {}
