# Fix #3 condition-(a) evidence: 15 failures pre-existing (DEEP-W4-D4)

Full suite WITH fix: 1343 passed, 15 failed, 1 skipped (613-617s).
All 15 are strict-mode run_budget/process-containment tests; zero failures
in bench/store/session/strategy/bridge tests.

## Commands (verbatim, cwd=/tmp/cryto-bot-w4-x1)
WITH fix:
  PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider --tb=no tests/acceptance/test_rel_integrated_challenge.py::test_rel_deadline_reparent_contained_or_refused tests/acceptance/test_rev2_acceptance.py::test_rev2_deadline_descendant_fix_or_refuse tests/runtime/test_nested_deadline_adversarial.py::test_handoff_nested_case_repeated tests/runtime/test_nested_deadline_adversarial.py::test_sigterm_ignorer_gets_sigkill tests/runtime/test_nested_deadline_adversarial.py::test_daemon_reparent_escape tests/runtime/test_nested_deadline_adversarial.py::test_inherited_pipe_blocks_caller_on_escape tests/runtime/test_nested_deadline_adversarial.py::test_rapid_fork_during_grace tests/runtime/test_nested_deadline_adversarial.py::test_enumeration_failure_must_not_fail_open tests/runtime/test_nested_deadline_adversarial.py::test_registry_kills_when_ps_dies_midrun tests/runtime/test_nested_deadline_adversarial.py::test_enumeration_hook_fail_closed tests/runtime/test_nested_deadline_adversarial.py::test_registry_hook_fail_after_midrun tests/runtime/test_nested_deadline_adversarial.py::test_child_output_relayed_verbatim tests/runtime/test_nested_deadline_adversarial.py::test_success_path_lingering_grandchild_does_not_hang_caller tests/runtime/test_nested_deadline_adversarial.py::test_shutdown_race_exit_at_deadline tests/unit/test_corr_review_acceptance.py::test_nested_budget_stops_descendants
WITHOUT fix (fix files stashed, then unstashed):
  git stash push -q src/cryptobot/bench_run.py tests/unit/test_bench_run.py
  PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider --tb=no tests/acceptance/test_rel_integrated_challenge.py::test_rel_deadline_reparent_contained_or_refused tests/acceptance/test_rev2_acceptance.py::test_rev2_deadline_descendant_fix_or_refuse tests/runtime/test_nested_deadline_adversarial.py::test_handoff_nested_case_repeated tests/runtime/test_nested_deadline_adversarial.py::test_sigterm_ignorer_gets_sigkill tests/runtime/test_nested_deadline_adversarial.py::test_daemon_reparent_escape tests/runtime/test_nested_deadline_adversarial.py::test_inherited_pipe_blocks_caller_on_escape tests/runtime/test_nested_deadline_adversarial.py::test_rapid_fork_during_grace tests/runtime/test_nested_deadline_adversarial.py::test_enumeration_failure_must_not_fail_open tests/runtime/test_nested_deadline_adversarial.py::test_registry_kills_when_ps_dies_midrun tests/runtime/test_nested_deadline_adversarial.py::test_enumeration_hook_fail_closed tests/runtime/test_nested_deadline_adversarial.py::test_registry_hook_fail_after_midrun tests/runtime/test_nested_deadline_adversarial.py::test_child_output_relayed_verbatim tests/runtime/test_nested_deadline_adversarial.py::test_success_path_lingering_grandchild_does_not_hang_caller tests/runtime/test_nested_deadline_adversarial.py::test_shutdown_race_exit_at_deadline tests/unit/test_corr_review_acceptance.py::test_nested_budget_stops_descendants
  git stash pop -q

## Test IDs (15)
- tests/acceptance/test_rel_integrated_challenge.py::test_rel_deadline_reparent_contained_or_refused
- tests/acceptance/test_rev2_acceptance.py::test_rev2_deadline_descendant_fix_or_refuse
- tests/runtime/test_nested_deadline_adversarial.py::test_handoff_nested_case_repeated
- tests/runtime/test_nested_deadline_adversarial.py::test_sigterm_ignorer_gets_sigkill
- tests/runtime/test_nested_deadline_adversarial.py::test_daemon_reparent_escape
- tests/runtime/test_nested_deadline_adversarial.py::test_inherited_pipe_blocks_caller_on_escape
- tests/runtime/test_nested_deadline_adversarial.py::test_rapid_fork_during_grace
- tests/runtime/test_nested_deadline_adversarial.py::test_enumeration_failure_must_not_fail_open
- tests/runtime/test_nested_deadline_adversarial.py::test_registry_kills_when_ps_dies_midrun
- tests/runtime/test_nested_deadline_adversarial.py::test_enumeration_hook_fail_closed
- tests/runtime/test_nested_deadline_adversarial.py::test_registry_hook_fail_after_midrun
- tests/runtime/test_nested_deadline_adversarial.py::test_child_output_relayed_verbatim
- tests/runtime/test_nested_deadline_adversarial.py::test_success_path_lingering_grandchild_does_not_hang_caller
- tests/runtime/test_nested_deadline_adversarial.py::test_shutdown_race_exit_at_deadline
- tests/unit/test_corr_review_acceptance.py::test_nested_budget_stops_descendants

## WITH-fix output (rc=1)
```
FFFFFFFFFFFFFFF                                                          [100%]
=========================== short test summary info ============================
FAILED tests/acceptance/test_rel_integrated_challenge.py::test_rel_deadline_reparent_contained_or_refused
FAILED tests/acceptance/test_rev2_acceptance.py::test_rev2_deadline_descendant_fix_or_refuse
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_handoff_nested_case_repeated
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_sigterm_ignorer_gets_sigkill
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_daemon_reparent_escape
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_inherited_pipe_blocks_caller_on_escape
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_rapid_fork_during_grace
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_enumeration_failure_must_not_fail_open
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_registry_kills_when_ps_dies_midrun
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_enumeration_hook_fail_closed
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_registry_hook_fail_after_midrun
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_child_output_relayed_verbatim
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_success_path_lingering_grandchild_does_not_hang_caller
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_shutdown_race_exit_at_deadline
FAILED tests/unit/test_corr_review_acceptance.py::test_nested_budget_stops_descendants
15 failed in 2.20s
```

## WITHOUT-fix output (rc=1)
```
FFFFFFFFFFFFFFF                                                          [100%]
=========================== short test summary info ============================
FAILED tests/acceptance/test_rel_integrated_challenge.py::test_rel_deadline_reparent_contained_or_refused
FAILED tests/acceptance/test_rev2_acceptance.py::test_rev2_deadline_descendant_fix_or_refuse
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_handoff_nested_case_repeated
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_sigterm_ignorer_gets_sigkill
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_daemon_reparent_escape
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_inherited_pipe_blocks_caller_on_escape
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_rapid_fork_during_grace
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_enumeration_failure_must_not_fail_open
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_registry_kills_when_ps_dies_midrun
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_enumeration_hook_fail_closed
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_registry_hook_fail_after_midrun
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_child_output_relayed_verbatim
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_success_path_lingering_grandchild_does_not_hang_caller
FAILED tests/runtime/test_nested_deadline_adversarial.py::test_shutdown_race_exit_at_deadline
FAILED tests/unit/test_corr_review_acceptance.py::test_nested_budget_stops_descendants
15 failed in 1.43s
```

## Verdict
Outputs identical except wall time (2.20s vs 1.43s): the same 15 fail
with and without fix #3. Root cause: branch predates mainline 18bd4ea
(enforce-or-refuse preflight); stale copies invoke strict run_budget
without --allow-best-effort and get REFUSED (125) on darwin instead of
running (124). run_budget.py byte-identical across branches. Zero round
impact: all 48 filed jobs carry --allow-best-effort; every completed job
shows enforcement=verified.
