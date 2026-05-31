#!/usr/bin/env python3
"""Fetch the proven-universe daily fixtures (indices + commodities) for EvoLab.

The playbook's fundable edge (HAC t=9, 21/21 eras) lives on diversified trend
across equity indices + commodities. yfinance `period='max'` gives decades of
daily OHLC for free (^GSPC = ~98y). Writes one fixture per symbol as a JSON list
of {t,o,h,l,c} rows (t = ms epoch), the shape evolab.universe's daily loader
reads. Re-runnable: overwrites with the latest history.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yfinance as yf

# yahoo ticker -> fixture stem. Commodities carry the =F continuous-future suffix.
SYMBOLS: dict[str, str] = {
    "^GSPC": "GSPC", "^IXIC": "IXIC", "^DJI": "DJI", "^RUT": "RUT",
    "^FTSE": "FTSE", "^GDAXI": "GDAXI", "^N225": "N225",
    "GC=F": "GC", "CL=F": "CL", "SI=F": "SI", "HG=F": "HG", "NG=F": "NG",
}

OUT_DIR = Path(__file__).resolve().parent.parent / "evolab" / "fixtures" / "proven"
MIN_BARS = 500  # reject a symbol that returned too little to score


def fetch_one(ticker: str) -> list[dict]:
    df = yf.Ticker(ticker).history(period="max", interval="1d")
    rows = []
    for ts, r in df.iterrows():
        o, h, l, c = float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"])
        if not all(map(lambda x: x == x, (o, h, l, c))):  # drop NaN rows
            continue
        rows.append({"t": int(ts.timestamp() * 1000), "o": o, "h": h, "l": l, "c": c})
    return rows


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok, thin, failed = [], [], []
    for ticker, stem in SYMBOLS.items():
        try:
            rows = fetch_one(ticker)
        except Exception as err:
            failed.append((stem, repr(err)))
            print(f"  FAIL {stem:<6} {ticker:<7} {err!r}")
            continue
        if len(rows) < MIN_BARS:
            thin.append((stem, len(rows)))
            print(f"  THIN {stem:<6} {ticker:<7} only {len(rows)} bars (<{MIN_BARS}) — skipped")
            continue
        (OUT_DIR / f"{stem}.json").write_text(json.dumps(rows))
        span = f"{_d(rows[0]['t'])}..{_d(rows[-1]['t'])}"
        print(f"  OK   {stem:<6} {ticker:<7} {len(rows):>6} bars  {span}")
        ok.append(stem)
    print(f"\nwrote {len(ok)} fixtures -> {OUT_DIR}"
          f"  ({len(thin)} thin, {len(failed)} failed)")
    return 0 if ok else 1


def _d(ms: int) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


if __name__ == "__main__":
    raise SystemExit(main())
