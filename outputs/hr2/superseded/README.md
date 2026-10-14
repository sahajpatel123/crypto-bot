# Superseded H-R2 v1 figures (REV2 R5)

These v1 outputs are SUPERSEDED and must never be cited as results.
Retained for provenance only.

v1 defects (review §3, "H-R2's execution timing is not causal"):
- Arrival = first quote at/after EVIDENCE time, not decision/arrival:
  all 60/60 filled rows fill BEFORE their candidate's evaluated_now_utc
  (median lead 1.5845s).
- Stop/target exits filled at triggering trade prints directly
  (trigger used as executable exit price).
- Final mark carried forward into unsupported later horizons.
- Funding excluded via an invented universal bound (≤0.01bp claim).

Corrected v2 figures: outputs/hr2/diagnostics.json + portfolio.json
+ extract_manifest.json (recomputed once under causal semantics;
see reports/REV2-R5.md and tools/hr2_diagnostic.py docstring).
