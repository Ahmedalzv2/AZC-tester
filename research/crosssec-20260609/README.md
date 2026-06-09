# Cross-sectional crypto momentum — fundability validation (2026-06-09)

Honest, OOS-first, Bonferroni-corrected, **adversarially re-derived** test of whether
the one crypto structure that ever survived fees (cross-sectional momentum) is fundable
in its most executable form. Verdict: **NO — confirmed dead-end** (registry sig `33474e8865c5`).

Data: 415 liquid MEXC perps, daily, 2020-12 → 2026-06-09 (refetched fresh; the prior
`t=3.73` headline was on data through 2026-06-01 and on the top-100 restriction).

## Experiments
- `e1_legs.py` — leg decomposition. Long leg is the IS carrier (full t=1.71) but **OOS-noise (t=-0.04)**; L/S spread best at OOS t=0.70; short book a net loser; reversal is the -0.99999 sign-flip twin.
- `e2_longonly_liquid.py` — executable form (long-only, top-100-liquid, EW-excess). full t=2.88, **OOS t=1.86 (<2)**; top-100 strengthens vs full (confirms playbook) but sub-2→sub-2.
- `e3_robustness.py` — 24-cell knob sweep. **0/24 clear OOS Bonferroni (3.078)**; 2/24 reach loose OOS t≥2 vs 19/24 IS full t≥2. Consistent positive region but underpowered, not a significant plateau.
- `e4_fees.py` — **fees are NOT the wall** (taker = 1.7% of gross at ~57%/wk turnover). Signal decay is.
- `e5_decay.py` — 2026 is mostly a **dispersion drought** (z=-1.06) with a **genuine-decay overlay** (2022 same dispersion stayed flat; 2026 prints -1.01%/period, ~0.96% below the dispersion-edge regression).
- `verify_e2_adversarial.py`, `verify_e3_adversarial.py` — from-scratch refutation (no shared code). E2 "fundable" claim REFUTED; E3 "too weak to fund" claim SURVIVED.

## The kill
- The +3.38%/wk mean is a **memecoin-pump fat tail**: drop best 5% of weeks → +0.13%/wk (t=0.11), median +0.32%/wk, 51% of weeks positive.
- **Survivorship-clean** (full-history names only) collapses it to full t=1.375 / +1.03%/wk.
- No lookahead (oracle-leak control runs ~4× larger). OOS is the honest 30% chronological holdout.

## Reproduce
`cd /root/apps/backtest-lab && .venv/bin/python research/crosssec-20260609/e2_longonly_liquid.py`
(needs `data_cache/mexc/` populated via `scripts/fetch_mexc_universe.py`).

Do **not** knob-mine the two loose-OOS cells (14/0.20/7, 7/0.10/14) — that is in-sample mining.
Do **not** fund or seed new capital. The free `mexc_crosssec_shadow` lane may keep logging as
the forward arbiter, but the prior is now strongly negative.
