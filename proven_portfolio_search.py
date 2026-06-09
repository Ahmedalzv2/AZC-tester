"""Portfolio-genome search on the proven managed-futures universe.

EvoLab's per-asset genome search is the wrong tool for the §1 edge: the
diversified equity-index + commodity TREND edge (t=9 over 100y) lives in the
PORTFOLIO, not any single market — per-asset proven search never clears the
deflated bar (playbook §1). This searches the portfolio-level knobs instead
(Donchian lookback, chandelier trail, vol target, vol-lookback), wrapping the
validated `portfolio_trend.build_portfolio` engine.

Discipline (non-negotiable, this is a SEARCH so it is a multiple-testing trap):
  - judge OUT-OF-SAMPLE (chronological holdout), never in-sample;
  - DEFLATE the winner's Sharpe by the number of configs tried (Bailey/Lopez de
    Prado DSR) so the search cannot manufacture an edge;
  - locate the prod config — a real edge is a robust PLATEAU, not a lone peak.

It is a robustness + improvement search on a KNOWN edge, not a new-edge hunt.
A config that "wins" must clear the deflated bar AND beat prod OOS to matter.
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from portfolio_trend import build_portfolio, DEFAULT_UNIVERSE
from stats import newey_west_tstat
from overfit import sharpe_moments, deflated_sharpe_ratio

PROD = {"don": 100, "trail": 5, "vol_target": 0.15, "vol_lookback": 60}
CACHE = Path(__file__).resolve().parent / "data_cache" / "proven"
ANN = math.sqrt(252.0)


def _series_stats(r: pd.Series) -> dict[str, float]:
    """Annualized Sharpe + HAC t-stat of a daily-return series."""
    x = r.dropna().to_numpy()
    m = sharpe_moments(x)
    return {
        "sharpe_ann": round(m["sharpe"] * ANN, 3),
        "hac_t": round(float(newey_west_tstat(x)), 3),
        "n": int(m["n"]),
        "per_obs_sharpe": m["sharpe"],
        "skew": m["skew"],
        "kurt": m["kurt"],
    }


def score_config(ohlc: dict[str, pd.DataFrame], *, don: int, trail: int,
                 vol_target: float, vol_lookback: int, oos_frac: float = 0.30) -> dict[str, Any]:
    """Build the portfolio for one genome; score full-sample and OOS holdout."""
    res = build_portfolio(ohlc, don=don, trail=trail, vol_target=vol_target, vol_lookback=vol_lookback)
    r = res.daily_returns.dropna()
    cut = int(len(r) * (1.0 - oos_frac))
    full, oos = _series_stats(r), _series_stats(r.iloc[cut:])
    return {
        "genome": {"don": don, "trail": trail, "vol_target": vol_target, "vol_lookback": vol_lookback},
        "full": {k: full[k] for k in ("sharpe_ann", "hac_t", "n")},
        "oos": {k: oos[k] for k in ("sharpe_ann", "hac_t", "n")},
        # per-obs OOS moments feed the deflation (selection is on the holdout)
        "per_obs_sharpe": oos["per_obs_sharpe"],
        "skew": oos["skew"],
        "kurt": oos["kurt"],
        "cagr_pct": res.metrics.get("cagr_pct"),
        "max_dd_pct": res.metrics.get("max_dd_pct"),
    }


def _neighbors(g: dict, grid: dict) -> list[dict]:
    """Configs differing from g by exactly one knob's adjacent grid value."""
    out = []
    for knob, vals in grid.items():
        if g[knob] not in vals:
            continue
        i = vals.index(g[knob])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                out.append({**g, knob: vals[j]})
    return out


def run_search(ohlc: dict[str, pd.DataFrame], grid: dict[str, list], *,
               prod: dict = PROD, oos_frac: float = 0.30) -> dict[str, Any]:
    """Score the full grid, rank by OOS Sharpe, deflate the winner, locate prod."""
    keys = ["don", "trail", "vol_target", "vol_lookback"]
    configs = [dict(zip(keys, combo)) for combo in itertools.product(*(grid[k] for k in keys))]
    scored = [score_config(ohlc, oos_frac=oos_frac, **c) for c in configs]
    scored.sort(key=lambda s: s["oos"]["sharpe_ann"], reverse=True)
    for rank, s in enumerate(scored, 1):
        s["oos_rank"] = rank

    best = scored[0]
    prod_entry = next((s for s in scored if all(s["genome"][k] == prod[k] for k in keys)), None)

    # Deflate the OOS winner by the OOS Sharpes of every config tried.
    trials = [s["per_obs_sharpe"] for s in scored]
    deflated = deflated_sharpe_ratio(best["per_obs_sharpe"], best["oos"]["n"],
                                     best["skew"], best["kurt"], trials)

    nb = _neighbors(best["genome"], grid)
    nb_sharpes = [s["oos"]["sharpe_ann"] for s in scored
                  if any(all(s["genome"][k] == n[k] for k in keys) for n in nb)]
    plateau = {
        "neighbor_count": len(nb_sharpes),
        "neighbor_oos_sharpe_mean": round(float(np.mean(nb_sharpes)), 3) if nb_sharpes else None,
        "neighbors_positive_share": round(float(np.mean([s > 0 for s in nb_sharpes])), 2) if nb_sharpes else None,
    }

    improve = (best["oos"]["sharpe_ann"] - prod_entry["oos"]["sharpe_ann"]) if prod_entry else None
    clears = deflated["dsr"] >= 0.95 and best["oos"]["hac_t"] >= 2.0
    if clears:
        verdict = "clears-deflated-bar"
    elif prod_entry and prod_entry["oos_rank"] <= max(3, len(scored) // 10) and (improve is None or improve < 0.10):
        verdict = "prod-near-optimal"
    elif improve is not None and improve >= 0.10:
        verdict = "robust-but-not-significant"
    else:
        verdict = "no-improvement"

    return {
        "universe": list(ohlc.keys()),
        "n_configs": len(scored),
        "oos_frac": oos_frac,
        "best_by_oos": best,
        "prod": prod_entry,
        "deflated": deflated,
        "plateau_of_best": plateau,
        "improvement_oos_sharpe_vs_prod": round(improve, 3) if improve is not None else None,
        "verdict": verdict,
        "ranked": scored,
    }


def load_universe(tickers: list[str] | None = None, *, refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Daily OHLC per ticker via yfinance period='max' (the §1 free data unlock),
    cached to data_cache/proven/. Network only on first run / --refresh."""
    import yfinance as yf
    tickers = tickers or DEFAULT_UNIVERSE
    CACHE.mkdir(parents=True, exist_ok=True)
    ohlc: dict[str, pd.DataFrame] = {}
    for t in tickers:
        fp = CACHE / f"{t}.csv"
        if fp.exists() and not refresh:
            df = pd.read_csv(fp, index_col=0)
            # CSV round-trip loses the dtype; coerce back to a DatetimeIndex or
            # build_portfolio's date math sees strings (silent until cached).
            df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
            df = df[df.index.notna()]
        else:
            df = yf.Ticker(t).history(period="max", interval="1d")[["Open", "High", "Low", "Close"]]
            df.to_csv(fp)
        if len(df) > 260:
            ohlc[t] = df
    return ohlc


def main() -> None:
    import sys
    grid = {
        "don": [50, 75, 100, 150, 200],
        "trail": [3, 5, 7],
        "vol_target": [0.10, 0.15, 0.20],
        "vol_lookback": [60],
    }
    ohlc = load_universe(refresh="--refresh" in sys.argv)
    print(f"universe: {len(ohlc)} tickers {list(ohlc)}", flush=True)
    rep = run_search(ohlc, grid)
    b, p = rep["best_by_oos"], rep["prod"]
    print(f"\nconfigs={rep['n_configs']}  oos_frac={rep['oos_frac']}")
    print(f"{'genome':<42}{'full_Sh':>8}{'full_t':>7}{'OOS_Sh':>8}{'OOS_t':>7}{'rank':>5}")
    for s in rep["ranked"]:
        g = s["genome"]
        tag = "  <-PROD" if g == {k: PROD[k] for k in g} else ("  <-BEST" if s is b else "")
        print(f"don{g['don']:>3} trl{g['trail']} vt{g['vol_target']:.2f} vl{g['vol_lookback']:<3}"
              f"{s['full']['sharpe_ann']:>13}{s['full']['hac_t']:>7}{s['oos']['sharpe_ann']:>8}"
              f"{s['oos']['hac_t']:>7}{s['oos_rank']:>5}{tag}")
    d = rep["deflated"]
    print(f"\nBEST by OOS: {b['genome']}  OOS Sharpe={b['oos']['sharpe_ann']} t={b['oos']['hac_t']}")
    print(f"PROD rank={p['oos_rank']}/{rep['n_configs']}  OOS Sharpe={p['oos']['sharpe_ann']} t={p['oos']['hac_t']}")
    print(f"improvement (best-prod) OOS Sharpe = {rep['improvement_oos_sharpe_vs_prod']}")
    print(f"DEFLATED: DSR={d['dsr']:.3f} (bar 0.95)  sr_star={d['sr_star']:.4f}  n_trials={d['n_trials']}")
    print(f"plateau of best: {rep['plateau_of_best']}")
    print(f"VERDICT: {rep['verdict']}")
    out = Path(__file__).resolve().parent / "research" / "proven-portfolio-search.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
