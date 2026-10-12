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
# layer; see commit). F-W5R1 (four-budget sizing) open below.
KNOWN_FAILURES = (
    # F-W5R1: sizing ignores remaining daily/floor budgets.
    "test_w5r1_remaining_budgets.py"
    "::test_entry_capped_by_remaining_daily_budget",
    "test_w5r1_remaining_budgets.py"
    "::test_entry_capped_by_floor_cushion",
)


def pytest_collection_modifyitems(items):
    for item in items:
        if any(item.nodeid.endswith(known) for known in KNOWN_FAILURES):
            item.add_marker(pytest.mark.xfail(
                strict=True, reason="48h finding open; remove when fix lands"))
