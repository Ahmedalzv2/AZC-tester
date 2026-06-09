"""Does BREADTH improve the proven trend portfolio? (honest, pre-registered)

The §1 edge is diversified trend. Real managed-futures funds trade 50+ markets;
ours trades 10. Adding *uncorrelated* markets is the documented way to lift a
trend portfolio's Sharpe — breadth, not knob-tuning, so it is overfitting-safe.

This is ONE pre-registered comparison, not a universe search: a principled broad
ETF set spanning equities(regions)/rates/commodities/credit/FX/real-assets vs the
10-ETF baseline, SAME genome grid (so DSR's trial count is identical), judged OOS
and DSR-deflated. A broader universe "wins" only if it lifts OOS Sharpe AND its
deflated DSR materially beats the baseline. Run: .venv/bin/python research/broaden_proven_universe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proven_portfolio_search import load_universe, run_search, PROD, DEFAULT_UNIVERSE  # noqa: E402

# Pre-registered broad managed-futures market set (liquid ETFs, fixed before the run).
BROAD = [
    # equities by region
    "SPY", "QQQ", "IWM", "EFA", "EEM", "EWJ", "VGK",
    # rates
    "TLT", "IEF", "SHY",
    # commodities (all sectors)
    "GLD", "SLV", "DBC", "USO", "UNG", "DBA", "CPER",
    # credit
    "HYG", "LQD",
    # FX / USD
    "UUP", "FXE", "FXY",
    # real assets
    "VNQ",
]

GRID = {"don": [50, 75, 100, 150, 200], "trail": [3, 5, 7], "vol_target": [0.10, 0.15, 0.20], "vol_lookback": [60]}


def _line(tag, rep):
    b, p = rep["best_by_oos"], rep["prod"]
    d = rep["deflated"]
    print(f"\n[{tag}] universe={len(rep['universe'])}  configs={rep['n_configs']}")
    print(f"  BEST  {b['genome']}  full_Sh={b['full']['sharpe_ann']} OOS_Sh={b['oos']['sharpe_ann']} OOS_t={b['oos']['hac_t']}")
    print(f"  PROD  OOS_Sh={p['oos']['sharpe_ann']} OOS_t={p['oos']['hac_t']} rank={p['oos_rank']}/{rep['n_configs']}")
    print(f"  DSR={d['dsr']:.3f} (bar 0.95)  sr_star={d['sr_star']:.4f}  plateau={rep['plateau_of_best']}")
    print(f"  best CAGR={b.get('cagr_pct')}% maxDD={b.get('max_dd_pct')}%")
    return b["oos"]["sharpe_ann"], d["dsr"], b["oos"]["hac_t"]


def main():
    base_ohlc = load_universe(DEFAULT_UNIVERSE)
    broad_ohlc = load_universe(BROAD)
    print(f"baseline universe loaded: {len(base_ohlc)}  broad loaded: {len(broad_ohlc)} {list(broad_ohlc)}")
    base = run_search(base_ohlc, GRID, prod=PROD)
    broad = run_search(broad_ohlc, GRID, prod=PROD)
    b_sh, b_dsr, b_t = _line("BASELINE-10", base)
    x_sh, x_dsr, x_t = _line("BROAD", broad)
    d_sh, d_dsr = round(x_sh - b_sh, 3), round(x_dsr - b_dsr, 3)
    print("\n==== VERDICT ====")
    print(f"OOS Sharpe: baseline {b_sh} -> broad {x_sh}  (Δ {d_sh:+})")
    print(f"OOS HAC t : baseline {b_t} -> broad {x_t}")
    print(f"DSR       : baseline {b_dsr:.3f} -> broad {x_dsr:.3f}  (Δ {d_dsr:+})")
    better = d_sh >= 0.10 and x_dsr > b_dsr
    clears = x_dsr >= 0.95 and x_t >= 2.0
    print(f"breadth helped materially (ΔSharpe>=0.10 & DSR up): {better}")
    print(f"broad clears the deflated bar (DSR>=0.95 & OOS t>=2): {clears}")
    import json
    out = Path(__file__).resolve().parent / "broaden-universe-result.json"
    out.write_text(json.dumps({"baseline": base, "broad": broad,
                               "delta_oos_sharpe": d_sh, "delta_dsr": d_dsr,
                               "breadth_helped": better, "clears_bar": clears}, indent=2, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
