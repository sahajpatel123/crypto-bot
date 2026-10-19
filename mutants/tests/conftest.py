"""Suite profiles: network-blocked default + public-data opt-in (W5-24H).

See tests/net_guard.py for the mechanism. Default runs block external
HTTP/socket (loopback allowed) and skip ``public_data``-marked tests;
``pytest --public-data`` (or CRYPTOBOT_PUBLIC_DATA=1) runs marked tests
unguarded while unmarked tests stay guarded.
"""
import os
import sys

sys.path.insert(0, str(__file__.rsplit("/", 1)[0]))

import pytest

import net_guard


def pytest_addoption(parser):
    parser.addoption(
        "--public-data", action="store_true", default=False,
        help="run public_data-marked integration tests unguarded")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "public_data: tests requiring real public-network access "
        "(opt-in profile only)")


def _opt_in(config) -> bool:
    return bool(config.getoption("public_data")
                or os.environ.get(net_guard.OPT_IN_ENV) == "1")


def pytest_collection_modifyitems(config, items):
    if _opt_in(config):
        return
    skip = pytest.mark.skip(
        reason="needs --public-data or CRYPTOBOT_PUBLIC_DATA=1")
    for item in items:
        if net_guard.MARKER in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _net_guard(request):
    if _opt_in(request.config) and net_guard.MARKER in request.keywords:
        yield  # opt-in profile + marked test: genuinely unguarded.
        return
    guard = net_guard.Guard().install()
    try:
        yield
    finally:
        guard.uninstall()
