"""OP-001 integration: open-finding probes are strict-xfail.

The 14 probes below FAIL on the pre-fix tree by design (each reproduces
a directive section-2 finding). They are marked xfail(strict=True) so the
suite stays green while the findings are open; when a fix lands, its
probes XPASS and the suite fails until this list is trimmed at that
fix's integration. (Manager integration fixup; probes authored by W5.)
"""
import pytest

# All 48h findings fixed (Q-008/E-009/manager). All 6 review-2 defects
# fixed: D1+D2 by W2-24H + manager P1/P2/P3, D3+D4 by W4-24H + manager
# §12 wiring, D5+D6 by W3-24H. D3/D4 probes were corrected at
# integration to the Required design (protected profile + tracker
# layer; see commit). F-W5R1 (four-budget sizing) fixed by the manager
# four-budget cap (policy computes remaining-daily/floor-cushion cap,
# sizing takes the min); probes now pass unmarked.
# 30min (W5): §4 IOC arrival-scheduling failures below, strict-xfail
# with owner; XPASS forces trim at each fix's integration.
KNOWN_FAILURES = (
    # Owner W1/W2: nonmarketable IOC rests and revives on later liquidity
    # instead of canceling at arrival (both sides).
    "test_ioc_adversarial.py"
    "::test_nonmarketable_buy_ioc_dead_at_arrival_no_late_revival",
    "test_ioc_adversarial.py"
    "::test_nonmarketable_sell_ioc_dead_at_arrival_no_late_revival",
    # Owner W1/W2: marketable IOC does not fill against the arrival book.
    "test_ioc_adversarial.py"
    "::test_marketable_ioc_fills_at_arrival_book_both_sides",
    # Owner W1/W2: price band not enforced at arrival (same root cause).
    "test_ioc_adversarial.py"
    "::test_price_band_bounds_the_cross_at_arrival",
)


def pytest_collection_modifyitems(items):
    for item in items:
        if any(item.nodeid.endswith(known) for known in KNOWN_FAILURES):
            item.add_marker(pytest.mark.xfail(
                strict=True, reason="48h finding open; remove when fix lands"))
