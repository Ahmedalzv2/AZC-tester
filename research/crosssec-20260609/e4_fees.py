"""E4 - FEE SURVIVAL of long-only top-decile momentum on the 100 most-liquid MEXC perps.

Hypothesis: low weekly turnover lets a long-only top-decile (look=14, hold=7,
frac=0.10) momentum book survive realistic taker fees.

Honest discipline (playbook hard rules):
  * signal uses only closes <= t; realised return measured t -> t+h     -> no lookahead
  * book = equal-weight top `frac` of the 100 most-liquid assets by momentum
  * turnover = sum_s |w_new - w_old| (L1 weight change) each rebalance
    fraction-of-book-replaced = turnover / 2 (a full rotation gives turnover=2)
  * fee charged on the L1 turnover at the per-LEG rate (entry/exit each one leg)
  * net period return series -> Newey-West (HAC) t; judged on the 70/30 OOS tail
  * THREE fee models compared, every number pinned to its model
      (a) taker       0.00075 / leg   <- the bankable bound
      (b) double-taker 0.0015 / leg   <- stress / adverse fill
      (c) maker        0.0002 / leg   <- resting-limit rotation (optimistic)
"""
from __future__ import annotations

import json
from pathlib import Path

from mexc_trend_hunt import DATA, hac_t, load

LOOKBACK = 14
HOLD = 7
FRAC = 0.10
TOP_LIQUID = 100

FEE_MODELS = {
    "taker_0.00075": 0.00075,
    "double_taker_0.0015": 0.0015,
    "maker_0.0002": 0.0002,
}


def top_liquid_syms(n: int) -> list[str]:
    """The n most-liquid symbols by median quote volume from the manifest."""
    man = json.loads((DATA / "_manifest.json").read_text())
    man = sorted(man, key=lambda m: m.get("med_qvol", 0), reverse=True)
    return [m["symbol"] for m in man[:n]]


def build_panel(syms: list[str]):
    by_sym = {}
    all_ts = set()
    for s in syms:
        try:
            bars = load(s)
        except FileNotFoundError:
            continue
        d = {b.ts: b.c for b in bars}
        by_sym[s] = d
        all_ts.update(d.keys())
    return sorted(all_ts), by_sym, [s for s in syms if s in by_sym]


def run(by_sym, syms, dates, *, lookback, hold, frac, fee):
    """Walk the calendar in `hold`-day steps. Long-only equal-weight top `frac`
    decile by trailing `lookback` momentum. Return (gross_rets, net_rets, turnovers)."""
    gross_rets: list[float] = []
    net_rets: list[float] = []
    turnovers: list[float] = []
    prev_w: dict[str, float] = {}
    t = lookback
    while t + hold < len(dates):
        d_now, d_past, d_fut = dates[t], dates[t - lookback], dates[t + hold]
        elig = []
        for s in syms:
            c = by_sym[s]
            if d_now in c and d_past in c and d_fut in c and c[d_past] > 0:
                elig.append((s, c[d_now] / c[d_past] - 1.0))
        if len(elig) < 20:
            t += hold
            continue
        elig.sort(key=lambda x: x[1])
        k = max(1, int(len(elig) * frac))
        winners = [s for s, _ in elig[-k:]]  # long-only TOP decile by momentum
        w = {s: 1.0 / k for s in winners}    # equal-weight long book, sums to 1
        gross = 0.0
        for s, wt in w.items():
            c = by_sym[s]
            gross += wt * (c[d_fut] / c[d_now] - 1.0)
        keys = set(w) | set(prev_w)
        turnover = sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in keys)
        net = gross - turnover * fee
        gross_rets.append(gross)
        net_rets.append(net)
        turnovers.append(turnover)
        prev_w = w
        t += hold
    return gross_rets, net_rets, turnovers


def oos_split(rets: list[float]):
    cut = int(len(rets) * 0.7)
    return rets[:cut], rets[cut:]


def main() -> None:
    syms_req = top_liquid_syms(TOP_LIQUID)
    dates, by_sym, syms = build_panel(syms_req)
    print(f"requested top-{TOP_LIQUID} liquid; loaded {len(syms)} with data; "
          f"{len(dates)} daily dates\n")

    # gross is fee-independent; compute once from any model run
    gross, _, turns = run(by_sym, syms, dates, lookback=LOOKBACK, hold=HOLD,
                          frac=FRAC, fee=0.0)
    n = len(gross)
    mean_turn = sum(turns) / len(turns) if turns else 0.0
    frac_replaced = mean_turn / 2.0  # L1=2 means full rotation
    g_mean = sum(gross) / n
    g_is, g_oos = oos_split(gross)
    print(f"periods (rebalances): {n}")
    print(f"mean L1 turnover/rebalance: {mean_turn:.4f}  "
          f"(= {frac_replaced*100:.1f}% of book replaced)")
    print(f"GROSS mean %/week: {g_mean*100:+.4f}%   "
          f"full-t={hac_t(gross):+.2f}  OOS-t={hac_t(g_oos):+.2f}\n")

    results = []
    print(f"{'fee_model':>22}{'per_leg':>10}{'net%/wk':>10}"
          f"{'full_t':>9}{'OOS_t':>9}{'fee%ofgross':>13}{'net+&OOSt+':>12}")
    for name, fee in FEE_MODELS.items():
        _, net, _ = run(by_sym, syms, dates, lookback=LOOKBACK, hold=HOLD,
                        frac=FRAC, fee=fee)
        net_mean = sum(net) / len(net)
        full_t = hac_t(net)
        _, net_oos = oos_split(net)
        oos_t = hac_t(net_oos)
        fee_drag = g_mean - net_mean  # mean fee cost per week
        fee_pct_of_gross = (fee_drag / g_mean * 100.0) if g_mean != 0 else float("nan")
        bankable = (net_mean > 0) and (oos_t > 0)
        results.append({
            "fee_model": name,
            "per_leg": fee,
            "periods": len(net),
            "net_mean_pct_wk": net_mean * 100,
            "full_t": full_t,
            "oos_t": oos_t,
            "oos_net_mean_pct_wk": (sum(net_oos) / len(net_oos)) * 100 if net_oos else 0.0,
            "fee_pct_of_gross": fee_pct_of_gross,
            "net_pos_and_oos_t_pos": bankable,
        })
        print(f"{name:>22}{fee:>10.5f}{net_mean*100:>+9.4f}%"
              f"{full_t:>+9.2f}{oos_t:>+9.2f}{fee_pct_of_gross:>+12.1f}%"
              f"{str(bankable):>12}")

    taker = next(r for r in results if r["fee_model"] == "taker_0.00075")
    verdict_taker = (taker["net_mean_pct_wk"] > 0) and (taker["oos_t"] > 0)
    print(f"\nVERDICT under realistic taker (0.00075/leg, the bankable bound):")
    print(f"  net %/week = {taker['net_mean_pct_wk']:+.4f}%  "
          f"OOS-t = {taker['oos_t']:+.2f}  -> net-positive AND OOS-t-positive: "
          f"{verdict_taker}")

    out = {
        "config": {"lookback": LOOKBACK, "hold": HOLD, "frac": FRAC,
                   "top_liquid": TOP_LIQUID, "loaded_assets": len(syms),
                   "periods": n},
        "turnover": {"mean_L1": mean_turn, "frac_book_replaced": frac_replaced},
        "gross": {"mean_pct_wk": g_mean * 100, "full_t": hac_t(gross),
                  "oos_t": hac_t(g_oos)},
        "fee_models": results,
        "verdict_taker_bankable": verdict_taker,
    }
    Path(__file__).resolve().parent.joinpath("e4_fees_results.json").write_text(
        json.dumps(out, indent=2))
    print("\nwrote e4_fees_results.json")


if __name__ == "__main__":
    main()
