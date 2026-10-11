"""Capability-matrix unit tests (Worker 2, E-001). Offline-safe, no network."""
from cryptobot.market_data import build_matrix, render_markdown
from cryptobot.market_data.capabilities import to_dict


def test_matrix_has_all_candidate_rows():
    names = [row.name for row in build_matrix()]
    assert names == ["stdlib-urllib", "nautilus_trader", "binance-connector", "ccxt"]


def test_stdlib_row_is_installed():
    (stdlib,) = [row for row in build_matrix() if row.name == "stdlib-urllib"]
    assert stdlib.installed_version is not None and "python" in stdlib.installed_version
    assert stdlib.proposed_pin is None  # interpreter-pinned, no PyPI pin.


def test_uninstalled_rows_verify_nothing_and_name_blockers():
    for row in build_matrix():
        if row.installed_version is None:
            assert row.verified == ()
            assert any("not installed" in b for b in row.blockers), row.name
            assert row.proposed_pin is not None  # pin proposal still recorded.


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
