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
    # FIXED by W1 arrival gate (f11e899) + manager query repairs (fdad744):
    # nonmarketable IOCs cancel at arrival (both sides, probes updated to
    # the ioc_artifact_corrected stat); marketable IOC restated to
    # tick-driven semantics (no fabrication on bare advance; arrival tick
    # fills at arrival prices) and green; price band green. All four run
    # unmarked.
    # Owner cloud-vega (data): research/selector cost split (26 vs 31 bps), unsigned
    # funding, implicit spread semantics (§5 unified contract).
    "test_cost_contract.py"
    "::test_research_selector_agree_on_frozen_inputs",
    "test_cost_contract.py"
    "::test_funding_sign_is_representable",
    "test_cost_contract.py"
    "::test_spread_semantics_are_explicit",
    # Owner cool-amalthea (runtime): no shipped 1s max-age profile; missing timestamps
    # crash instead of blocking; no feed-independent control path.
    "test_runtime_controls.py"
    "::test_operational_profile_enforces_one_second_max_age",
    "test_runtime_controls.py"
    "::test_missing_event_timestamps_fail_closed",
    "test_runtime_controls.py"
    "::test_control_path_recognizes_stop_despite_blocked_producer",
)


def pytest_collection_modifyitems(items):
    for item in items:
        if any(item.nodeid.endswith(known) for known in KNOWN_FAILURES):
            item.add_marker(pytest.mark.xfail(
                strict=True, reason="48h finding open; remove when fix lands"))
