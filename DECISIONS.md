# Decisions and evidence log

Manager: young-polaris. Workers: exactly three peer sessions (see coord/workers.json).
Model configuration: owner requested Muse Spark 1.3 Max-effort. Available session
tools do not expose model version/effort settings for inspection (env shows no
SPARK/1.3/EFFORT variables; no Muse model-config command verified). Recorded as
unverified; no substitution claimed. Identity per session: Muse Code powered by
Meta Muse Spark.

## CEO initial decisions (simulation defaults, not proven settings)

- M0 run mode: replay/offline simulation; live-feed paper next.
- Python + pinned NautilusTrader after bounded connector-capability check; thin
  official Binance SDK connector only on demonstrated blocking incompatibility.
  One production engine, not two.
- Modular single-process application; no distributed microservices/heavy frontend
  without measured need.
- Position mode one-way; future pilot proposal isolated margin, auto-add off.
  Never alter unrelated account positions/configuration.
- One open position globally in initial pilot design, including in-flight reservations.
- Planned per-trade loss budget: at most 0.25% of reconciled trading equity
  incl. stressed loss-side execution costs (approx Rs 25 at Rs 10,000).
- Leverage cap 3x initial; higher leverage separately validated later.
- Operational daily loss circuit breaker: 1% decline from starting-day marked
  equity (flow-adjusted) blocks new entries rest of accounting day + exposure
  reduction. Persistent across restart; next day needs reconciliation + healthy
  system. Trigger, not guaranteed limit.
- Profit-protection simulation candidate: retain 70% of global net realised
  gains after gains reach 1% of original pilot equity; threshold upward-only,
  preserved across days/restarts; flows separate. Test alternatives offline.
- New-entry pause at 2% daily net-liquidation-equity target in initial simulation
  policy; manage open exposure normally. Evaluate continued trading under profit
  protection separately. No late-day size inflation.
- Accounting day Asia/Kolkata 00:00-24:00; raw events UTC. Ledger USDT primary,
  INR display separate.
- No withdrawal credentials, transfers, paid subs, publication or live orders.

## Manager decisions (M0)

- D-001: Repo initialised at workspace root (was empty, no git). Branch main.
  Remote to be added only for the owner-named private repo at commit time.
- D-002: Shared coordination directory `coord/` outside any worker worktree/branch.
  Task states: assigned, running, blocked, review, accepted. See coord/README.md.
- D-003: File ownership to prevent competing edits (contract v0.1.0):
  - Manager: CONTRACTS.md, DECISIONS.md, coord/, tools/m1_*, src/cryptobot/coordination/,
    src/cryptobot/__init__.py, pyproject/README/test bootstrap, reports/.
  - Worker 1 (Quant): specs/strategies/, src/cryptobot/strategies/,
    src/cryptobot/features/, src/cryptobot/research/, tests/unit/test_strategies_*.
  - Worker 2 (Data/Execution): src/cryptobot/market_data/,
    src/cryptobot/execution/, tools/capture_*, tools/replay_*, data/README,
    tests/unit/test_execution_*, tests/unit/test_market_data_*.
  - Worker 3 (Risk/Verification): src/cryptobot/risk/, src/cryptobot/accounting/
    (ledger review), tests/acceptance/, tests/fixtures/, specs/acceptance*.
    Risk code requires manager review + another worker reproducing critical
    invariants; strategy profitability never self-certified.
- D-004: M1 scaffold lives in manager-owned tools/m1_vertical_slice.py with inline
  stubs labelled synthetic; worker modules replace stubs via contracts. No manager
  edits inside worker-owned implementation files.
- D-005: NautilusTrader version pin deferred until Worker 2 capability matrix
  lands (bounded check). No framework code in M1 scaffold.
- D-006: Workers may write exactly their own completion file
  (coord/outbox/Q-001.json, E-001.json, V-001.json); the rest of coord/
  stays manager-owned. Uncommitted-branch-diff evidence is acceptable for
  review when a worker's git policy requires user authorization to commit;
  the manager reviews the diff and the worker commits if/when authorized.
