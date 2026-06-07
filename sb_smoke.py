import sys
import pandas as pd
sys.path.insert(0, "/root/apps/backtest-lab")
from engine import run_backtest

df = pd.read_csv("/root/apps/backtest-lab/data_cache/^NDX_5m_yahoo.csv")
df["time"] = pd.to_datetime(df["time"], utc=True)
df = df.set_index("time").sort_index()
df = df[["Open", "High", "Low", "Close", "Volume"]]
print("bars:", len(df), "| range:", df.index[0], "->", df.index[-1])

code = open("/root/apps/backtest-lab/silver_bullet_code.py").read()
res = run_backtest(df, "custom_python", params={}, custom_code=code, interval="5m", fee_bps=2)
m = res.metrics
print("=== METRICS ===")
for k in ["total_return_pct", "cagr_pct", "sharpe", "max_drawdown_pct", "win_rate_pct", "num_trades", "profit_factor", "avg_trade_pct"]:
    if k in m:
        print(" ", k, "=", m[k])
print("metric keys:", list(m.keys()))
print("trades:", len(res.trades))
for tr in res.trades[:4]:
    print("  ", tr)
if len(res.trades) > 4:
    print("   ...")
    for tr in res.trades[-2:]:
        print("  ", tr)
