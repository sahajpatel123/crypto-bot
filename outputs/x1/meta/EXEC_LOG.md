## 2026-10-14 ~22:05 UTC (job 3 running) — bridge/prune procedure locked
- Bridge reads fills from ckpt work/engine_journal.jsonl + intents from store.db.
  Dev ckpt was pruned to bench_checkpoint.json + stop_cursor.json BEFORE the fixed
  bridge ran => dev fills/intents evidence lost from ckpt dir.
- Saving facts: dev j1 report booked all-zero + taker_bps=5.0>0 PROVES fills=[].
  intents_admitted unprovable from pruned dir => deterministic REDO of filed job-1
  command (same seed/code/data) after val chain completes; compare redo report vs
  backup with MATCH-only output; bridge dev from redo artifacts; then prune.
- DISCIPLINE SLIP (recorded honestly): mechanics inspection of dev j1 report
  displayed its booked block (one cell net seen). No discretion exists downstream
  (all jobs filed, selection by frozen tool), so no bias can enter; all future
  inspections redact booked.*. Final report will disclose this.
- Rule from here: BRIDGE EACH CELL AT CHAIN END, THEN PRUNE. Per-cell subset
  manifests (mechanical filter of frozen manifest) + per-cell out dirs, assemble
  at end (comparison+rundir per cell; coverage.json merged by sorted concat —
  coverage.json is audit-only, unread by frozen tools). Manifest itself untouched.
## 2026-10-14 ~22:30 UTC — disk relief via own caches
- Free was 484M before job 4 (~84M margin). Pruned own-user regenerable caches:
  ~/.npm 3.4G -> 296M (cacache clean + _npx rm; npm trailing chown nit ignored),
  uv cache prune REFUSED (lock held by peers' live `uv run` servers/workers;
  did NOT --force). codex-runtimes/opencode untouched (other harnesses).
- Free now 3.7G. Job 4 (~400M) safe. After job 4: bridge val cell + prune chain
  (~2.5G back), then dev redo, then continue jobs 5-48 one at a time.
## 2026-10-14 ~22:45 UTC — OWNER STOP executed
- No live jobs of mine at stop (bridge had completed rc=0; only foreign
  proc is another session's deep-w1-d2 pytest — left alone). Jobs 5-48 NOT run.
- Evidence committed 1cc77dd, pushed deep/w4-x1 (b15d906..1cc77dd).
  Bulky val journals + store.db kept on disk only (resume-capable, uncommitted).
- State filed: coord/outbox/DEEP-W4-D4.stopped.json. No economics/select run;
  no selection outcome; round incomplete by owner stop, not screen rule.
## Interruption window (manager condition a)
- HELD 2026-10-14 ~22:45 UTC -> ~23:35 UTC on re-surfaced Oct 12-13 user stop
  orders. No jobs ran in the window; jobs 1-4 evidence + val bridge preserved
  (commit 1cc77dd; coord/outbox/DEEP-W4-D4.stopped.json stands as the record).
- Manager ruling (young-polaris): RESUME under all existing authorizations.
  Grounds: Oct 12-13 stops superseded by Oct-14 'Continue' + dispatch; owner
  in manager session confirmed no stop ordered. Conditions accepted: (a) this
  disclosure, (b) continue from checkpoints, redo only if mechanically
  required + disclosed, (c) TEST burned / EVAL sealed / caps + freeze
  unchanged, (d) NEW local stop naming this round -> halt + report.
- Mechanically-required redo (disclosed): dev j1 rerun (filed job-1 argv
  verbatim) to restore journals pruned before the fixed bridge; without it
  the dev bridge would fabricate intents_admitted=0. MATCH-verified vs backup.
## Timezone correction (all prior entries)
- Machine local = IST (UTC+5:30). Every earlier '... UTC' wall-clock label in
  this log was actually IST. True-UTC mapping: stop ~17:15, provenance answer
  ~17:55, hold window 2026-10-14 ~17:15 -> ~18:00 UTC, resume ~18:05 UTC.
  Session-log-derived user-message timestamps were true UTC and stand.
## Dev redo result (mechanical, disclosed)
- Redo (filed job-1 argv verbatim, fresh dir, replayed=0) ran FURTHER than orig:
  2,120,483 vs 1,594,049 ingested; commits 1063 vs 800; cursor same day
  2026-09-13, seqs BTC 320604/ETH 430049 vs 104995/119224. Same 900.0s wall
  budget + stop reason => machine-throughput variance (2356 vs 1771 ev/s),
  not nondeterminism. Identity fields all MATCH (script-verified, rc=0).
- REDO report now at filed path (bridged evidence); ORIG report preserved at
  outputs/x1/meta/orig_X1-R1_dev_j1.json + git history. Manifest still valid
  (paths frozen, not contents). Dev bridge rc=0; chain pruned post-bridge.
  Pruned-orig ckpt dir (84K) kept on disk only at .../X1-R1_dev_pruned_orig/.
