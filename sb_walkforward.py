import sys
import pandas as pd
sys.path.insert(0, "/root/apps/backtest-lab")
from walkforward import walk_forward

CSV = "/root/apps/backtest-lab/data_cache/USATECHIDXUSD_5m_dukascopy.csv"
df = pd.read_csv(CSV)
df["time"] = pd.to_datetime(df["time"], utc=True)
df = df.set_index("time").sort_index()
df = df[["Open", "High", "Low", "Close", "Volume"]]
print("DATA:", len(df), "bars |", df.index[0], "->", df.index[-1], flush=True)
code = open("/root/apps/backtest-lab/silver_bullet_code.py").read()
FEE = 2.0

def show(label, params):
    out = walk_forward(df, "custom_python", params=params, oos_fraction=0.3,
                       fee_bps=FEE, custom_code=code, interval="5m", iterations=1500)
    print(f"\n===== {label}  params={params} =====", flush=True)
    for name in ("in_sample", "out_sample"):
        leg = out.get(name, {})
        m = leg.get("metrics", {})
        print(f"  [{name}] ret%={m.get('total_return_pct')} trades={m.get('trade_count')} "
              f"win%={m.get('win_rate_pct')} sharpe={m.get('sharpe')} PF={m.get('profit_factor')}", flush=True)
    print("  decay:", out.get("decay"), "| holds_out_of_sample:", out.get("holds_out_of_sample"), flush=True)

show("PRIMARY bias+PD rr2 ema20", {"rr": 2.0, "ema_period": 20, "pd_filter": 1})
show("bias-only (no PD) rr2 ema20", {"rr": 2.0, "ema_period": 20, "pd_filter": 0})
show("bias+PD rr2 ema10", {"rr": 2.0, "ema_period": 10, "pd_filter": 1})
show("bias+PD rr1.5 ema20", {"rr": 1.5, "ema_period": 20, "pd_filter": 1})
show("bias+PD rr3 ema20", {"rr": 3.0, "ema_period": 20, "pd_filter": 1})
print("\nALL DONE", flush=True)
