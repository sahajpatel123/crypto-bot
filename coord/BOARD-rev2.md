# Completion board — review f8f6a76 follow-through (rev2)

Starting SHA: `f8f6a76bdf2e48d177d228956721661502eb74a6` (matches reviewed
revision; newer work: none — tree clean plus the review file itself).
Integration branch: `rev2/integration` (base `2625346`).
Probes reproduced 1:1 at start (`/tmp/rev2/probes.out`, exit 1).

| # | Requirement | Owner | State | Acceptance command | Evidence | SHA |
|---|---|---|---|---|---|---|
| R1 | Thread-owned event handoff: pump thread never touches Session/SQLite; bounded supervised queue; overflow/apply-failure/lag halt entries, keep evidence | W1 | dispatched | new regression tests + probe case green | — | — |
| R2 | Fill recoverable until booking acked; no premature transport dedup; recovery finds terminal-order fills; crash boundaries (pre-receipt/pre-booking/pre-protection) without dupes/resubmits | W1 | dispatched | same | — | — |
| R3 | Halt independence: stream heal clears only its own reason | W1 | dispatched | same | — | — |
| R4 | Demo `full` truthful: nonzero unless all pass; failed/blocked preflight prevents entry; normal Session entry/protection/exit + stream interruption + restart/adoption + authoritative reconcile | W2 | dispatched | `demo_drill.py full` offline BLOCKED; fault-injection suite | — | — |
| R5 | H-R2 causal correction: no fill before decision; trigger≠executable exit; quote-age/coverage rules; unscorable horizons; funding unknown-not-zero; recompute once, archive old | W4→? | W4 retry pending | corrected diagnostics + audit | — | — |
| R6 | Finite investigation: 1 hypothesis + ≤4 new versioned configs + CASH + baseline, ≤12 dev/val cells, frozen selection, honest NO/INSUFFICIENT if applicable | W4→? | W4 retry pending | registry + report | — | — |
| R7 | Data feasibility audit: Tardis sample + legal sources; channels/timestamps/gaps/funding/filters/license/cost; per-family support; exact missing input or purchase choice | W3 | dispatched | audit report + manifests | — | — |
| R8 | Independent adversarial acceptance via real default command paths + Linux deadline repro/portability decision | W5 | dispatched | acceptance run on RC | — | — |
| R9 | One acceptance artifact: machine-readable engineering/demo/economic/production statuses on one SHA | manager | pending | acceptance command | — | — |

Next action: collect worker ACKs; retry/reassign W4 within 5 min; manager owns R9 + integration.
