"""OP-001 integration: open-finding probes are strict-xfail.

The 14 probes below FAIL on the pre-fix tree by design (each reproduces
a directive section-2 finding). They are marked xfail(strict=True) so the
suite stays green while the findings are open; when a fix lands, its
probes XPASS and the suite fails until this list is trimmed at that
fix's integration. (Manager integration fixup; probes authored by W5.)
"""
import pytest

KNOWN_FAILURES = (
    # Finding 1: future-VWAP quotes (labels guard passes unmarked).
    "test_finding_1_future_vwap.py"
    "::test_modeled_quote_uses_only_causal_trades",
    "test_finding_1_future_vwap.py"
    "::test_future_mutation_does_not_change_earlier_quotes",
    # Finding 2: mark close published at open.
    "test_finding_2_mark_close.py::test_close_not_published_at_open",
    "test_finding_2_mark_close.py::test_open_close_availability_preserved",
    "test_finding_2_mark_close.py::test_joined_marks_preserve_availability",
    # Finding 3: cross-symbol dedup.
    "test_finding_3_dedup.py::test_cross_symbol_identical_quotes_preserved",
    "test_finding_3_dedup.py::test_legitimate_repeated_updates_preserved",
    "test_finding_3_dedup.py::test_conflicting_duplicates_detected",
    # Finding 4: gap-bar quality.
    "test_finding_4_gap_quality.py"
    "::test_gap_bar_not_usable_as_clean_strategy_bar",
    "test_finding_4_gap_quality.py::test_session_view_propagates_gap_quality",
    "test_finding_4_gap_quality.py::test_recovery_requires_causal_warmup",
    # Finding 5: select-stranded frames.
    "test_finding_5_select_strand.py::test_coalesced_second_frame_stranded",
    "test_finding_5_select_strand.py"
    "::test_buffered_message_drained_without_readability",
    "test_finding_5_select_strand.py"
    "::test_fragmented_ping_burst_and_quiet_routes",
)


def pytest_collection_modifyitems(items):
    for item in items:
        if any(item.nodeid.endswith(known) for known in KNOWN_FAILURES):
            item.add_marker(pytest.mark.xfail(
                strict=True, reason="48h finding open; remove when fix lands"))
