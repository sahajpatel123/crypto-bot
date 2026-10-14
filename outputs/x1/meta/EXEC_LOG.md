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
