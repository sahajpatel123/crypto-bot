# D1 — amendment 3: trial-bound audit and fail-closed DSR status

This strengthening amendment is frozen before any D1 return, forward price change, event count, power estimate, or P&L is computed. Bind it with the frozen D1 specification and amendments 1 and 2. It supersedes their program-level N values and is the sole source for the evaluator's `N_TRIALS` decision. It does not alter D1's signal, grid, universe, execution, costs, statistics, or gates.

## Decision: no finite N_TRIALS is established

`N_TRIALS` remains `None`; do not compute or emit DSR and do not allow a D1 PASS while it is unset. A finite upper bound cannot be proven from the current preregistration text and available run evidence. In particular, preregistrations require counting invalid/voided scored runs, but set no maximum on observed aborted/restarted attempts. A missing execution log is not evidence that such an attempt did not occur. The earlier amendment-1 residual inventory is also not fully reconciled to unique historical keys (as amendment 2 already disclosed). Therefore no finite integer inferred from that inventory is a defensible upper bound.

An independent review of the proposed `N=1187` calculation confirmed its arithmetic and that the DSR multiplier rises with N, but rejected 1187 as a provable upper bound for the reasons above. This amendment does not adopt 1187. The reviewer also identified a conflict in H6's declared base hypotheses and an uncounted C2-VM secondary-look opportunity; both are included in the conservative documented subtotal below, but they do not cure the unbounded retry/history gap.

## Documented design-opportunity subtotal (not N_TRIALS)

The table counts every documented H/B grid cell for every preregistered fold/split and one confirmation opportunity, whether run or not. It uses all bases named anywhere in H6's text to avoid resolving its contradiction in the less conservative direction. This is a reproducible subtotal of declared opportunities, not an upper bound on historical scored trials and must not be used by the evaluator.

| Family/configuration set | Cells / bases | Folds or splits per cell | Confirmations per cell | Subtotal |
|---|---:|---:|---:|---:|
| H1 maker OFI | 27 | 3 | 1 | 27 × 4 = 108 |
| H2 trend/vol | 27 | 3 | 1 | 27 × 4 = 108 |
| H3 funding skew | 27 | 3 | 1 | 27 × 4 = 108 |
| H4 cross-venue | 18 | 3 | 1 | 18 × 4 = 72 |
| H5 liquidation cascade | 27 | 3 | 1 | 27 × 4 = 108 |
| H6 volatility filter | 27 × 4 named bases (H1, H2, H3, H4) | 3 | 1 | 27 × 4 × 4 = 432 |
| H3-on-H2 filter application | 1 | counted once by H3 §31 | counted once by H3 §31 | 1 |
| **H subtotal** |  |  |  | **937** |
| B1 vol-scaled trend | 12 | 3 | 1 | 12 × 4 = 48 |
| B2 cross-sectional momentum | 6 | 3 | 1 | 6 × 4 = 24 |
| B3 funding carry | 8 | 3 | 1 | 8 × 4 = 32 |
| B4 basis | 9 | 3 | 1 | 9 × 4 = 36 |
| B5 extreme move | 8 | 3 | 1 | 8 × 4 = 32 |
| B6 OI divergence | 8 | 3 | 1 | 8 × 4 = 32 |
| B7 low-vol tilt | 8 | 3 | 1 | 8 × 4 = 32 |
| **B subtotal** | **59** |  |  | **236** |
| Amendment-1 non-H/B inventory |  |  |  | 230 |
| C2-VM secondary test at any of 3 possible C2 looks (C2-forward-amendment-1) | 1 per possible look |  |  | +3 |
| **Documented design-opportunity subtotal** |  |  |  | **937 + 236 + 230 + 3 = 1406** |

The 230 amendment-1 non-H/B subtotal is: earlier fixed H2/H3 evaluations 3; H2-HIST universe evaluations 2; H4 vol-ranked 1; H5 alternate maker-OFI 1; H1 book-capture 1; H5 alternate-OFI capture 1; Family C daily 4; C1-B4b DEV-sanity plus its separate forward confirmation 5; C2-forward looks 4; C2 holdout plus replication 2; voided B4 screen 1; pre-prereg S/X1/H-R2/EXP-001/EXP-002 trials 189; D1 taker cells 8; D1 maker diagnostic cells 8. Arithmetic: `3+2+1+1+1+1+4+5+4+2+1+189+8+8=230`; the pre-prereg subtotal is `14+24+1+90+60=189`.

H6's exact rules name H1/H3 for mean-reversion and H2/H4 for continuation; its grid paragraph separately says H2/H3 only. Counting all four named bases is conservative for the documented subtotal, but the source rule remains inconsistent and is not silently rewritten here. C2-forward amendment 1 defines a C2-VM secondary test at the C2 crossing look; because any of its three looks could be the crossing look, the subtotal adds all three potential C2-VM look trials. The 230 legacy inventory is carried from amendment 1 and is expressly not independently reconciled to unique historical run keys by amendment 2.

No H/B run-key manifest was found in the targeted execution-log filename check; the only manifest path found was `trials/x1-run-manifest.json`, which is X1-specific and does not establish H/B or restart completeness. No run or market-data contents were opened for this audit. The table includes all declared cells/folds/splits/confirmations and the known C2-VM look variants, but cannot cap unlogged or unbounded repeated scored attempts. Consequently 1406 is not an N_max and cannot replace `None`.

## DSR direction

For finite N, the registered multiplier is `q(N) = (1−g)Φ⁻¹(1−1/N) + gΦ⁻¹(1−1/(N·e))`, with `g=0.5772156649`, and `SR0 = sqrt(V) × q(N)`. Both probabilities increase with N and `Φ⁻¹` is increasing, so q(N) is increasing. Therefore a proven finite upper bound would be conservative: using it raises or preserves SR0 and cannot ease the DSR gate. The numerical value `q(1187)=3.3035583220` (unit variance) is an arithmetic illustration only, not the adopted penalty, because 1187 is not a proven upper bound. `Φ⁻¹(0.975)=1.9599639845≈1.9600` is the quantile sanity check. With no finite N_TRIALS, the evaluator must fail closed: DSR is not evaluable and PASS is impossible.

## Evidence boundary

This amendment uses preregistration text, source-file names, and independent review only. No D1 returns, forward price changes, event counts, power estimates, P&L, market-data contents, or holdout contents were read or computed. The sealed holdout remains untouched; evaluation stops at DEV.
