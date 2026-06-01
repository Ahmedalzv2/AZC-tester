"""Fetch the full MEXC USDT-perp daily universe into data_cache/mexc/.

Why daily: MEXC Day1 klines reach back ~5.5y (2000 bars) and daily is the
lowest-turnover timeframe, so it is the only crypto bar that has a chance of
surviving the 7.5bp taker fee wall that killed every intraday crypto test.

Why the whole universe: we had only ever tested ~25 majors. The inefficient
low-caps are exactly where a fee-surviving trend edge is most likely to live.

Output: one CSV per symbol (ts,open,high,low,close,vol_quote). A manifest
records bar count + median daily quote volume so the hunt can liquidity-filter.
"""
from __future__ import annotations

import csv
import json
import time
import urllib.request
from pathlib import Path
from statistics import median

BASE = "https://contract.mexc.com/api/v1"
OUT = Path(__file__).resolve().parent.parent / "data_cache" / "mexc"
MIN_BARS = 400          # ~13 months of daily data; drop newer/dead listings
MIN_MED_QVOL = 50_000   # USDT median daily quote volume; drop illiquid junk


def _get(url: str, tries: int = 4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "azc-tester/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - network flake, retry
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def usdt_perps() -> list[str]:
    d = _get(f"{BASE}/contract/detail")
    return [x["symbol"] for x in d["data"] if x.get("quoteCoin") == "USDT"]


def fetch_daily(symbol: str) -> list[tuple]:
    d = _get(f"{BASE}/contract/kline/{symbol}?interval=Day1")["data"]
    if not d or not d.get("time"):
        return []
    rows = []
    for i in range(len(d["time"])):
        rows.append((
            int(d["time"][i]),
            float(d["open"][i]), float(d["high"][i]),
            float(d["low"][i]), float(d["close"][i]),
            float(d["amount"][i]),  # quote volume (USDT)
        ))
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    syms = usdt_perps()
    print(f"{len(syms)} USDT perps from MEXC", flush=True)
    manifest = []
    kept = dropped = 0
    for n, sym in enumerate(syms, 1):
        try:
            rows = fetch_daily(sym)
        except Exception as e:  # noqa: BLE001
            print(f"  [{n}/{len(syms)}] {sym} FETCH-ERR {e}", flush=True)
            time.sleep(0.25)
            continue
        med_qv = median([r[5] for r in rows]) if rows else 0.0
        if len(rows) < MIN_BARS or med_qv < MIN_MED_QVOL:
            dropped += 1
        else:
            path = OUT / f"{sym}.csv"
            with path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["ts", "open", "high", "low", "close", "vol_quote"])
                w.writerows(rows)
            manifest.append({"symbol": sym, "bars": len(rows), "med_qvol": round(med_qv)})
            kept += 1
        if n % 50 == 0:
            print(f"  [{n}/{len(syms)}] kept={kept} dropped={dropped}", flush=True)
        time.sleep(0.12)  # be polite to the public endpoint
    manifest.sort(key=lambda x: -x["med_qvol"])
    (OUT / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"DONE kept={kept} dropped={dropped} -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
