from __future__ import annotations
import sys
from pathlib import Path
from engine_bracket import Bar
from evolab.search import run_search
from evolab.store import Store
from data_source import fetch_history


def to_bars(df):
    out = []
    for ts, row in df.iterrows():
        out.append(Bar(t=int(ts.timestamp()), o=float(row["Open"]), h=float(row["High"]),
                       l=float(row["Low"]), c=float(row["Close"])))
    return out


def main():
    symbol   = sys.argv[1] if len(sys.argv) > 1 else "ETHUSDT"
    interval = sys.argv[2] if len(sys.argv) > 2 else "15m"
    years    = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    gens     = int(sys.argv[4]) if len(sys.argv) > 4 else 30
    pop      = int(sys.argv[5]) if len(sys.argv) > 5 else 30
    tag      = sys.argv[6] if len(sys.argv) > 6 else f"{symbol}-{interval}"
    df, src = fetch_history(symbol=symbol, interval=interval, years=years, provider="binance")
    bars = to_bars(df)
    ds = src.get("dataset", {})
    print(f"loaded {len(bars)} bars {symbol} {interval} via {src.get('provider')} "
          f"{ds.get('start')}..{ds.get('end')} | gens={gens} pop={pop}", flush=True)
    store = Store(Path(__file__).resolve().parent / f"state-binance-{tag}")
    res = run_search(symbol, bars, generations=gens, pop_size=pop, seed=0, store=store)
    print("=== RESULT", symbol, interval, "===", flush=True)
    print("new_champion:", res.get("new_champion"))
    champ = res.get("champion")
    print("champion:", champ if champ else "none cleared the deflated OOS gate yet")


if __name__ == "__main__":
    main()
