"""Capability-matrix unit tests (Worker 2, E-001/E-002/E-006). Offline-safe, no network."""
from cryptobot.market_data import build_matrix, render_markdown
from cryptobot.market_data.capabilities import (
    E002_TRIAL_EVIDENCE,
    E002_TRIAL_VERDICT,
    E006_TRIAL_EVIDENCE,
    E006_TRIAL_VERDICT,
    E006_VERIFIED,
    to_dict,
)


def test_matrix_has_all_candidate_rows():
    names = [row.name for row in build_matrix()]
    assert names == ["stdlib-urllib", "nautilus_trader", "binance-connector", "ccxt"]


def test_stdlib_row_is_installed():
    (stdlib,) = [row for row in build_matrix() if row.name == "stdlib-urllib"]
    assert stdlib.installed_version is not None and "python" in stdlib.installed_version
    assert stdlib.proposed_pin is None  # interpreter-pinned, no PyPI pin.


def test_uninstalled_rows_name_blockers_and_qualify_any_verification():
    for row in build_matrix():
        if row.installed_version is None:
            assert any("not installed" in b for b in row.blockers), row.name
            assert row.proposed_pin is not None  # pin proposal still recorded.
            # Trial-venv evidence is allowed only when every entry names its venv.
            assert all(".venv-trial" in v for v in row.verified), row.name


def test_every_row_separates_verified_from_assumed():
    for row in build_matrix():
        assert isinstance(row.verified, tuple)
        assert isinstance(row.assumed, tuple)
        assert row.assumed, f"{row.name} must document its assumptions"


def test_extra_verified_evidence_flows_into_rows():
    matrix = build_matrix({"stdlib-urllib": ["GET fapi exchangeInfo 200 (observed)"]})
    (stdlib,) = [row for row in matrix if row.name == "stdlib-urllib"]
    assert stdlib.verified == ("GET fapi exchangeInfo 200 (observed)",)
    assert all("no behaviour verified" not in b for b in stdlib.blockers)


def test_render_and_dict_cover_all_rows():
    matrix = build_matrix()
    text = render_markdown(matrix)
    for row in matrix:
        assert row.name in text
    payload = to_dict(matrix)
    assert payload["contract_version"] == "v0.1.0"
    assert len(payload["rows"]) == 4


def test_e002_trial_history_preserved():
    (nautilus,) = [row for row in build_matrix() if row.name == "nautilus_trader"]
    assert E002_TRIAL_VERDICT == "blocked-on-transfer"
    for note in E002_TRIAL_EVIDENCE:
        assert note in nautilus.trial, "E-002 evidence must stay on the nautilus row"
    text = render_markdown(build_matrix())
    assert E002_TRIAL_VERDICT in text


def test_e006_trial_smoke_verified_with_venv_qualification():
    (nautilus,) = [row for row in build_matrix() if row.name == "nautilus_trader"]
    assert E006_TRIAL_VERDICT == "import-adapter-smoke-passed"
    for note in E006_TRIAL_EVIDENCE:
        assert note in nautilus.trial
    for claim in E006_VERIFIED:
        assert claim in nautilus.verified
    assert all(".venv-trial" in v for v in nautilus.verified)
    if nautilus.installed_version is None:  # normal case: suite runs under project .venv.
        assert any("not installed in project .venv" in b for b in nautilus.blockers)
    text = render_markdown(build_matrix())
    assert E006_TRIAL_VERDICT in text
    payload = to_dict(build_matrix())
    (row,) = [r for r in payload["rows"] if r["name"] == "nautilus_trader"]
    assert row["trial"] and len(row["verified"]) == len(E006_VERIFIED)
