# Adjudication table

Status: FROZEN before the recorder for this phase is started.
Committed before any launchd job is loaded. Machine consumer:
`cryptobot adjudicate`. This file is not edited after the first
adjudication record is appended.

## Clock

- T0 = timestamp of the first sealed recorder chunk in the recorder
  manifest. Until that chunk exists, the deadline is unset and
  adjudicate does not force-close anything.
- T = T0 + 90 days.

## Who is judged

Family A: H1–H6. Family C: C1. Family B is already KILLED and stays
in the negative set. A hypothesis whose artifacts are marked
SYNTHETIC cannot move the project to a real final state.

## Early stop

If every hypothesis in Families A and C is already in a terminal
state, adjudicate runs at that moment instead of waiting for T.
Terminal states: KILLED, FAIL, IMPRACTICAL, NOT_ESTABLISHED, PASS.

## Force-close at T

Every hypothesis that is not terminal becomes NOT_ESTABLISHED.
AWAIT_DATA and UNDERPOWERED are the expected cases. NOT_ESTABLISHED
counts as no edge. The force-close is an adjudication record. It
does not edit a prereg and it does not edit a verdict file.

## Project decision

Apply the first matching row.

| Final state | When | What the machine does |
|---|---|---|
| ARCHIVE_NEGATIVE | Every hypothesis is KILLED, FAIL, IMPRACTICAL, or NOT_ESTABLISHED | Unload every cryptobot launchd job, stop the recorder, write FINAL_VERDICT.md, post a macOS notification |
| PAPER_ONLY | At least one hypothesis is PASS, and the existing gate is not GO | Keep only the passing hypotheses in paper for 30 more days. No live orders |
| READY_FOR_HUMAN_DECISION | The existing gate code returns GO | Post a macOS notification. Do not arm. Arming stays a human at a TTY |

SYNTHETIC inputs never produce ARCHIVE_NEGATIVE, PAPER_ONLY, or
READY_FOR_HUMAN_DECISION as a real decision. The chain records a
refusal instead.

## Idempotence

Each run appends to a hash chain. A second run with the same inputs
and the same decision does not append a second decision and does
not repeat the unload.
