# IBKR paper micro-futures lane — setup

Validates the **futures execution path** for the proven trend portfolio's liquid
core, on an IBKR **paper** account. Complementary to the Alpaca ETF paper lane
(which holds the full universe incl. the EFA/EEM/DBC/TLT legs that have no micro
future). No real money — hard-guarded to `DU…` paper accounts only.

## Architecture
- `ibkr_futures.py` — pure planner: target weights → integer micro-contract
  buy/sell deltas + ETF→future map + `DU` paper-guard. Unit-tested.
- `ibkr_client.py` — `ib_async` wrapper over the IB **socket** API (paper port
  4002). Dry-run default. **Untested until a live Gateway session exists.**
- `run_paper_ibkr.py` — daily runner (mirror of `run_paper.py`). NAV →
  `ibkr-nav.jsonl`.

Universe map (micro front-month): SPY→MES, QQQ→MNQ, IWM→M2K, GLD→MGC, USO→MCL,
SLV→SIL. Gap (no micro future, Alpaca-only): EFA, EEM, DBC, TLT.

## Connection — IB Gateway + IBC in Docker (headless)
`ib_async` needs IB **Gateway**'s socket (4002 paper), NOT IBeam's Client Portal
REST. Use the `gnzsnz/ib-gateway` image (bundles IB Gateway + IBC auto-login +
Xvfb), running in **paper** mode.

1. Create `execution/.env.ibkr` (gitignored — never commit creds):
   ```
   TWS_USERID=<your IBKR paper username>
   TWS_PASSWORD=<your IBKR paper password>
   TRADING_MODE=paper
   ```
   Prefer a dedicated **paper-only** login (IBKR Client Portal → Settings →
   Paper Trading) over the live username, so live creds never touch the VPS.

2. Run the gateway (exposes paper socket on 4002):
   ```
   docker run -d --name ib-gateway --restart unless-stopped \
     --env-file execution/.env.ibkr \
     -p 127.0.0.1:4002:4002 \
     gnzsnz/ib-gateway:latest
   ```
   Bind to 127.0.0.1 only — the socket has no auth; never expose it publicly.

3. First login may need a one-time 2FA approval in the IBKR mobile app. IBKR
   force-logs-out daily (~midnight ET); IBC auto-restarts the session.

## Run
```
# dry-run (no orders; needs the gateway up for live equity/prices)
.venv/bin/python -m execution.run_paper_ibkr

# place paper orders
.venv/bin/python -m execution.run_paper_ibkr --live-paper
```
Daily cron (after US close), mirroring the Alpaca timer — add only once the
connection is verified:
```
35 21 * * 1-5  cd /root/apps/backtest-lab && .venv/bin/python -m execution.run_paper_ibkr --live-paper >> /var/log/ibkr-paper.log 2>&1
```

## Discipline (unchanged)
Paper only. No live capital until the forward t-stat clears ~2 (playbook hard
rule #1). This lane EXISTS to help build that forward track record on the
cheaper futures vehicle — it does not authorise live trading.
