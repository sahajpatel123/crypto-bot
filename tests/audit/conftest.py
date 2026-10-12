"""OP-001 integration: open-finding probes are strict-xfail.

The 14 probes below FAIL on the pre-fix tree by design (each reproduces
a directive section-2 finding). They are marked xfail(strict=True) so the
suite stays green while the findings are open; when a fix lands, its
probes XPASS and the suite fails until this list is trimmed at that
fix's integration. (Manager integration fixup; probes authored by W5.)
"""
import pytest

# All 5 findings fixed: 1+3 by Q-008, 2/4/5 core by E-009, residuals
# (ts-first marks, session gap view, has_pending fallback) by manager.
# Review-2 (W5-24H): 6 open defects below, strict-xfail until each fix
# lands and its probes XPASS (then trim at that fix's integration).
# The D5 redelivery guard passes unmarked (no-overcorrection pin).
KNOWN_FAILURES = (
    # D1: future snapshots visible at replay startup.
    "test_review2_d1_future_snapshot.py"
    "::test_asof_query_excludes_future_snapshot",
    "test_review2_d1_future_snapshot.py"
    "::test_future_snapshot_mutation_does_not_affect_earlier_query",
    # D2: false live synchronization report.
    "test_review2_d2_live_sync_report.py"
    "::test_prime_reports_actual_sync_state_not_fetch_success",
    # D3: event controls disabled.
    "test_review2_d3_event_controls.py"
    "::test_operational_configs_enable_events",
    "test_review2_d3_event_controls.py"
    "::test_anomaly_policy_has_runtime_caller",
    # D4: calendar freshness renewed without fetching.
    "test_review2_d4_calendar_freshness.py"
    "::test_fetched_timestamp_preserved_across_reload",
    "test_review2_d4_calendar_freshness.py"
    "::test_reread_without_verification_is_not_fresh",
    # D5: cross-symbol fill loss.
    "test_review2_d5_cross_symbol_fills.py"
    "::test_distinct_symbol_same_trade_id_both_booked",
    # D6: unknown-outcome block lost on restart.
    "test_review2_d6_unknown_restart.py"
    "::test_recovery_rebuilds_unknown_block",
    "test_review2_d6_unknown_restart.py"
    "::test_recovery_replays_fills_idempotently",
)


def pytest_collection_modifyitems(items):
    for item in items:
        if any(item.nodeid.endswith(known) for known in KNOWN_FAILURES):
            item.add_marker(pytest.mark.xfail(
                strict=True, reason="48h finding open; remove when fix lands"))
