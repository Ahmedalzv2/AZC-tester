# AZC strategy-test prompt template

This is the contract the AZC platform fills in for each strategy it wants tested.
Paste a filled copy into the VPS Claude CLI and run `/test-strategy` — the agent
implements it, backtests it, iterates until the edge is real (or ~8 attempts),
and reports an honest verdict.

Keep it short. Only the **Hypothesis** is strictly required; everything else has
a sane default the agent will assume and state.

```
STRATEGY TEST REQUEST

Asset / symbol:    e.g. BTC-USD (Yahoo) or BTCUSDT (local_file)
Data provider:     yahoo | local_file (+ file path)
Timeframe:         1d | 1h | 15m | 5m            (default 1d)
History:           years, e.g. 5                  (default 5)

Hypothesis:        1-2 sentences — the edge idea in plain words.
                   e.g. "Buy when price reclaims the 20-day high after an
                   oversold RSI; the breakout-from-fear move tends to follow through."

Entry / exit:      (optional) specifics if you have them, else let the agent decide.
Direction:         long-only | short-only | both   (default both)
Parameters:        (optional) ranges to explore, e.g. lookback 10-50, rsi 25-35
Fees:              bps per side, e.g. 7            (default 7)

Constraints:       (optional) e.g. max DD <= 30%, min 50 trades
Success criteria:  default = statistically real (|t| >= 2, p < 0.05) AND holds
                   out-of-sample. Override here if AZC wants something stricter.
```

## Filled example

```
STRATEGY TEST REQUEST
Asset / symbol:  BTC-USD
Data provider:   yahoo
Timeframe:       1d
History:         5 years
Hypothesis:      Trend-follow — go long when the 20-day momentum is positive and
                 price is above its 50-day average; flat otherwise.
Direction:       long-only
Parameters:      fast 10-30, slow 40-80
Fees:            7 bps
Success criteria: real edge that holds out-of-sample
```

The agent loop, tooling, and stop rule live in
`.claude/skills/test-strategy/SKILL.md`.
