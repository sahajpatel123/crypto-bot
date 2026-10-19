# 48h-baseline evidence (pre-directive, from /tmp)

Preserved 12 Oct 2026 ~18:40 IST. Superseded by the 48h directive; kept for
provenance. Bulky reproducible run dirs (captures/, runs/, journals, sqlite)
were dropped; small canonical artifacts + probe scripts retained. Hashes in
SHAINDEX.txt (sha256, 12 hex).

- m1_e008_main.json — M1 vertical slice on post-E-008 main, exit 0.
- e008_probe.py — 5 manager engine probes (all green at E-008 integration).
- e008_replay.py — frozen-day pump+engine replay proof (green).
- v002_probe.py — earlier engine probe script.
- v007_r1/, v007_r2/ — V-007 sample report builds (byte-identical pair).
- mgr-paper-001-analysis/ — full analysis of paper run mgr-paper-001
  (built from a blank→unknown migrated COPY; original run dir untouched).
- q7verify/quotes/ — synth 21-cell comparison, PRE-FIX (all positions died
  in protection-emergency-close; SUPERSEDED, kept as F3 evidence).
- q7verify/det1+det2/ — pre-fix determinism pair (6 fills, identical).
- q7verify/post1..post4/ — post-fix determinism pairs (38 fills, identical).
- q7verify/capmech/ — captured 400k BTC mechanism (0/0/0, no crash).

Repro (from repo root, locked env):
  uv run --locked python -m cryptobot.research.backtest --dataset synth_quotes \
    --out /tmp/q7req --config configs/paper.toml   # post-fix numbers
  uv run --locked python tools/m1_vertical_slice.py --out /tmp/m1.json
  uv run --locked python -m cryptobot.cli report --run-dir runs/mgr-paper-001
