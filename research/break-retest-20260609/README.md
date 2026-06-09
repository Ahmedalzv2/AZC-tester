# break_retest — break-and-retest continuation (2026-06-09)

Mechanised from the YouTube video [WEyJ-zKAEoA](https://www.youtube.com/watch?v=WEyJ-zKAEoA)
("Forex Trading Was Hard, Until I Discovered This"). The one testable claim in
that video is **break and retest with a rejection candle**; the rest ("candle
strength by placement", wicks "telling a story", "respected HTF signals") is
discretionary narrative that can't be specified without inventing free
parameters, so it was not tested.

## Signal (no-lookahead, `bracket_signals.break_retest`)

A recent bar (within `brW`) closes beyond an `brL`-bar level; the confirmation
bar `i` taps back into that level (within `brTolAtr * ATR`) and closes back
through it in the breakout direction. Only the freshest breakout is considered.
Evaluated on the closed bar `i`; entry at `i+1` open via the shared bracket
engine. Unit-tested in `tests/test_bracket_signals.py`.

## Method (playbook discipline)

- Deep 4h AZC crypto-perp tapes, 25 assets (`evolab.data`).
- **All-taker fees** 0.075%/leg (`engine_bracket` TAKER) — no maker fiction.
- Pre-registered 16-config grid (committed in `probe.py` before any result).
- Params **selected in-sample**, each asset's IS winner **judged once OOS**.
- **Bonferroni** across the basket: survivor must clear `t = 2.81`
  (α = 0.05 / 20 judged), not the naive 2.0.

## Verdict: NOT fundable

- 0 survivors. Best OOS t = **1.31** (ARB, "marginal") — below even the naive 2.0.
- 23/24 "noise", 1 "marginal". 12/24 positive OOS meanR ≈ a coin flip.
- Highest IS t-stats (ARB 2.19, BNB 1.81) did not carry out-of-sample.

Consistent with the prior: break-and-retest is a flavor of crypto
trend-continuation, an already-dead fee-wall lane. Recorded in the rejection
registry (`lanes/rejected-strategies.jsonl`, signature `dc936a0920e6`) so it is
never re-tuned. **Did not touch the platform** — nothing earned a shadow lane.

Reproduce: `.venv/bin/python research/break-retest-20260609/probe.py`
