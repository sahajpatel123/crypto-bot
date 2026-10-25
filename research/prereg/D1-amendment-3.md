# D1 — amendment 3: conservative program-level DSR trial bound

This strengthening amendment is frozen before any D1 return, forward price change, event count, power estimate, or P&L is computed. Bind it with the frozen D1 specification and amendments 1 and 2. It supersedes their program-level N values and their statement that DSR is not evaluable for lack of an exact historical N. It does not alter D1 signals, cells, universe, execution, costs, statistics, or gates.

The evaluator's single input is `N_TRIALS = 1187`, the conservative upper bound below. Exact historical N is not required. If the realized number of distinct decision-informing trials is at most this bound, using 1187 cannot weaken the DSR gate. The absence of a complete historical run-key manifest is not grounds to lower this constant.

## Counting rule

Count each distinct frozen configuration for every separately declared evaluation window that could have informed a choice. For H1–H6 this means each grid cell on each of its three registered DEV folds and its one-shot confirmation. For B1–B7 it means each grid cell on each of the three registered walk-forward test splits and its one-shot confirmation. All preregistered cells are included whether run, unrun, aborted, or restarted. An identical retry of the same configuration/window is not a new independent configuration; a changed setting or separate scored window is counted as its own row. The registered grids and windows below are exhaustive; an undocumented distinct configuration or look would invalidate this bound and must fail closed pending a new preregistration. No run record is treated as evidence that an allowed cell or window did not run.

H6 has 27 filter parameter cells and is registered on both H2 and H3: count 54 filtered configurations. H3's separate H3-on-H2 filter is counted once, as its preregistration specifies. No H-family fold boundary is inferred or dated here; the three preregistered fold identities are counted as three opportunities. B-family dated splits are listed in amendment 2 and each counts separately. Each family has one separately declared confirmation opportunity; this arithmetic counts that opportunity without opening or evaluating any confirmation/holdout data.

## Upper-bound crosswalk

| Family/configuration set | Grid/config cells | DEV folds / walk-forward splits per cell | One-shot confirmation per cell | Count |
|---|---:|---:|---:|---:|
| H1 maker OFI | 27 | 3 | 1 | 27 × (3 + 1) = 108 |
| H2 trend/vol | 27 | 3 | 1 | 27 × (3 + 1) = 108 |
| H3 funding skew | 27 | 3 | 1 | 27 × (3 + 1) = 108 |
| H4 cross-venue | 18 | 3 | 1 | 18 × (3 + 1) = 72 |
| H5 liquidation cascade | 27 | 3 | 1 | 27 × (3 + 1) = 108 |
| H6 volatility filter on H2 and H3 | 27 × 2 bases = 54 | 3 per filtered config | 1 per filtered config | 54 × (3 + 1) = 216 |
| H3-on-H2 filter application | 1 | counted once per H3 §31 | counted once per H3 §31 | 1 |
| **H subtotal** |  |  |  | **721** |
| B1 vol-scaled trend | 12 | 3 | 1 | 12 × (3 + 1) = 48 |
| B2 cross-sectional momentum | 6 | 3 | 1 | 6 × (3 + 1) = 24 |
| B3 funding carry | 8 | 3 | 1 | 8 × (3 + 1) = 32 |
| B4 basis | 9 | 3 | 1 | 9 × (3 + 1) = 36 |
| B5 extreme move | 8 | 3 | 1 | 8 × (3 + 1) = 32 |
| B6 OI divergence | 8 | 3 | 1 | 8 × (3 + 1) = 32 |
| B7 low-vol tilt | 8 | 3 | 1 | 8 × (3 + 1) = 32 |
| **B subtotal** | **59** |  |  | **236** |
| **Other program inventory from amendment 1** |  |  |  | **230** |
| **N_TRIALS upper bound** |  |  |  | **721 + 236 + 230 = 1187** |

The 230 non-H/B inventory is reproducible from amendment 1's crosswalk and is not multiplied by H/B fold rules: earlier fixed H2/H3 evaluations 3; H2-HIST universe evaluations 2; H4 vol-ranked 1; H5 alternate maker-OFI 1; H1 book-capture 1; H5 alternate-OFI capture 1; Family C daily 4; C1-B4b DEV-sanity plus its separate forward confirmation 5; C2-forward looks 4; C2 holdout plus replication 2; voided B4 screen 1; pre-prereg S/X1/H-R2/EXP-001/EXP-002 trials 189; D1 taker cells 8; D1 maker diagnostic cells 8. Arithmetic: `3+2+1+1+1+1+4+5+4+2+1+189+8+8 = 230`. The pre-prereg subtotal is `14+24+1+90+60 = 189`. The separately stated C2 and C1-B4b windows remain distinct as in amendment 1; identical source configurations are not duplicated beyond those declared looks.

The H/B subtotals re-add as follows: H1–H5 `(27+27+27+18+27)×4 = 504`; H6 `27×2×4 = 216`; H3-on-H2 `1`; hence H `504+216+1=721`. B ` (12+6+8+9+8+8+8)×4 = 59×4=236`. Full arithmetic is `504+216+1+236+230=1187`. This counts every declared cell and evaluation window, not only historical runs shown in incomplete logs. No market-data, return, or holdout contents were accessed to construct this table. No H/B run-key manifest was used to reduce the count.

## DSR penalty and conservative direction

D1's registered multiplier is `q(N) = (1−g)Φ⁻¹(1−1/N) + gΦ⁻¹(1−1/(N·e))`, with `g=0.5772156649`; `SR0 = sqrt(V) × q(N)`. Since both quantile probabilities increase with N and `Φ⁻¹` is increasing, q(N) increases with N. Therefore `N_TRIALS=1187` gives a null benchmark at least as high as any realized count `N≤1187`; this strengthens the gate, and uncertainty about exact N cannot make it easier.

| N used | `Φ⁻¹(1−1/N)` | `Φ⁻¹(1−1/(N·e))` | `q(N)` when `Var(SR)=1` |
|---:|---:|---:|---:|
| 470 (old floor; not used) | 2.8586 | 3.1623 | 3.0339 |
| 1187 (`N_TRIALS`) | 3.1408 | 3.4228 | **3.3036** |
| 1470 (direction check) | 3.2029 | 3.4805 | 3.3631 |

Arithmetic at the frozen bound: `(1−0.5772156649)×3.1407913981 + 0.5772156649×3.4227777227 = 3.3035583220`; thus `SR0 = 3.3035583220×sqrt(V)`. The normal-quantile sanity check is `Φ⁻¹(0.975)=1.9599639845≈1.9600`. For comparison, the former floor 470 would set the normalized bar 0.2696806895 Sharpe units lower than the 1187 bound. D1's realized `V`, SR0, and DSR require the future DEV evaluation and are not computed here; the gate is now evaluable once that permitted evaluation runs.

## Evidence boundary

This is a preregistration-only strengthening. No D1 returns, forward price changes, event counts, power estimates, P&L, market-data files, or holdout contents were read or computed. The sealed holdout remains untouched; the evaluator still stops after DEV. A later evaluator must use this file's `N_TRIALS` value exactly and must not substitute 470, 442, or an inferred smaller count.
