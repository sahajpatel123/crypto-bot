"""OP-001 integration: open-finding probes are strict-xfail.

The 14 probes below FAIL on the pre-fix tree by design (each reproduces
a directive section-2 finding). They are marked xfail(strict=True) so the
suite stays green while the findings are open; when a fix lands, its
probes XPASS and the suite fails until this list is trimmed at that
fix's integration. (Manager integration fixup; probes authored by W5.)
"""
import pytest

KNOWN_FAILURES = (
    # Finding 1 fixed by Q-008 (causal-first-trade-v1); entries trimmed.
    # Finding 2: 2/3 fixed by E-009 v2 freeze (trimmed); close-at-open open.
    "test_finding_2_mark_close.py::test_close_not_published_at_open",
    # Finding 3 fixed by Q-008 (venue-aware dedup); entries trimmed.
    # Finding 4: 2/3 fixed by E-009 gap fix (trimmed); session view open.
    "test_finding_4_gap_quality.py::test_session_view_propagates_gap_quality",
    # Finding 5: 2/3 fixed by E-009 fair drain (trimmed); no-readability open.
    "test_finding_5_select_strand.py"
    "::test_buffered_message_drained_without_readability",
)


def pytest_collection_modifyitems(items):
    for item in items:
        if any(item.nodeid.endswith(known) for known in KNOWN_FAILURES):
            item.add_marker(pytest.mark.xfail(
                strict=True, reason="48h finding open; remove when fix lands"))
