# AZC → EvoLab strategy-testing gateway

EvoLab exposes a one-off **honest verdict** endpoint. AZC submits a strategy; the
lab runs it through the fee-accurate truth layer (in-sample / out-of-sample,
HAC t-stat, bootstrap p) and returns `real` / `marginal` / `noise`.

This is research only — it never executes anything. It is a *verdict, not a
green light*: a strategy is still only a hypothesis until a live forward test.

## Endpoint

```
POST /api/evolab/verdict
Content-Type: application/json
```

Base URL: `http://localhost:3015` (same host) or
`https://backtest.srv1688368.hstgr.cloud` (public).

### Request

```json
{
  "family": "donchian_break",
  "params": {"don": 20, "atrN": 14, "atrMult": 2.0, "trail": 3, "erMin": 0.0, "regimeN": 20},
  "asset": "SOL",
  "oos_fraction": 0.30
}
```

- `family` — one of the lab's strategy families. AZC mapping:
  - `azc_trend` (donchian breakout + ATR trail + ER regime gate) → **`donchian_break`**
    with `trail` set and optional `erMin`/`regimeN`.
  - `azc_meanrev` (band fade) → **`donchian_fade`** or **`bollinger_fade`** (`rr` set).
  - Other families: `ts_momentum`, `ma_cross`, `rsi_reversion`, `bollinger_break`.
- `params` — family params. Fees (all-taker) and trail-exit `rr` are applied by
  the engine; you do not send fee params.
- `asset` — a crypto-perp with mounted tape (currently `SOL`, `DOGE`, `XRP`).
- `oos_fraction` — held-out fraction (default 0.30).

### Response

```json
{
  "verdict": "noise",
  "family": "donchian_break",
  "asset": "SOL",
  "net_R_oos": -1.83,
  "is":  {"n": 540, "meanR": 0.061, "t": 1.42},
  "oos": {"n": 232, "meanR": -0.008, "t": -0.31, "p": 1.0, "holds": false},
  "fees": "all-taker (engine_bracket TAKER model)",
  "deflation": "none (single hypothesis — not a multiple-testing search)",
  "note": "A verdict, not a green light. Still only a hypothesis until a live forward test."
}
```

- `verdict`:
  - **real** — OOS n≥40, OOS meanR>0, IS meanR>0, OOS t≥2.0, OOS p<0.05.
  - **marginal** — OOS positive with t≥1.0 but not significant.
  - **noise** — everything else (the common, honest result).
- `oos.holds` — OOS edge survives at ≥50% of the in-sample edge (no collapse).

### Errors

- `400` — unknown/unmounted asset, unknown family, or params the strategy can't run.
- `503` — EvoLab engine not available on the host (the backtest engine isn't
  importable here). The verdict endpoint runs only where the engine is installed.

## Examples

curl:
```bash
curl -s -X POST http://localhost:3015/api/evolab/verdict \
  -H 'content-type: application/json' \
  -d '{"family":"donchian_break","params":{"don":20,"atrN":14,"atrMult":2.0,"trail":3,"erMin":0.0,"regimeN":20},"asset":"SOL"}'
```

Node (AZC side):
```js
const r = await fetch("http://localhost:3015/api/evolab/verdict", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ family: "donchian_break", params: {...}, asset: "SOL" }),
});
const verdict = await r.json();
```

## Notes

- One call = one hypothesis, so **no multiple-testing deflation** is applied. If
  AZC sweeps many configs, account for that on the AZC side (or expect more false
  `real`s the more you submit) — deflation across a search is what the EvoLab
  daemon does internally, not this endpoint.
- The endpoint is read-only and stateless; it does not enroll the strategy into
  the continuous /evolab search (that was deliberately left out of scope).
