"""Seed the rejection registry with the playbook §3 already-disproven strategies.

Idempotent: skips any signature already present. Run once to bootstrap the
graveyard so future studies/lanes auto-skip what we already know is dead, instead
of rediscovering it. Each entry mirrors a documented finding in
/root/trading-knowledge/STRATEGY-PLAYBOOK.md §3.
"""
from __future__ import annotations

from lanes import registry

SEED_DATE = "2026-05-30"  # when these were established in the playbook

KNOWN_DEAD = [
    dict(kind="scalp_fvg", params={"timeframe": "5m", "type": "fvg_retest"},
         venue="mexc", asset="multi-crypto",
         reason="fee-dead: net-negative after 0.0755% taker on all 27 assets; "
                "fees ran 215% of gross; live lane -$3.94 over 31 trades (29% WR)",
         metrics={"verdict": "dead", "fee_model": "taker"}),
    dict(kind="mean_rev", params={"type": "donchian_fade", "tf": "4h"},
         venue="mexc", asset="multi-crypto",
         reason="significantly NEGATIVE on 5y crypto, HAC t≈-2.8; only LTC fade-positive",
         metrics={"hac_t": -2.8}),
    dict(kind="trend", params={"type": "donchian", "tf": "1d"},
         venue="fx", asset="majors+GBPJPY",
         reason="every param combo net-negative on 5y daily, t down to -4.67; "
                "2021-26 FX regime choppy/mean-reverting, whipsaws breakouts",
         metrics={"hac_t": -4.67}),
    dict(kind="trend", params={"type": "donchian"},
         venue="mexc", asset="LTC",
         reason="LTC is trend-poison (only mean-rev-positive symbol); exclude from trend basket",
         metrics={"verdict": "poison"}),
    dict(kind="alpha_factor", params={"family": "alpha101+gtja191", "tf": "1h"},
         venue="mexc", asset="multi-crypto",
         reason="faint gross signal, DEAD after 7.5bps taker (t=-3..-12); daily "
                "resample kills fees but signal evaporates (best t=0.17) — dead both ways",
         metrics={"fee_model": "taker"}),
]


def main() -> int:
    added = 0
    for d in KNOWN_DEAD:
        sig = registry.signature(d["kind"], d["params"], d["venue"], d["asset"])
        hit, _ = registry.is_rejected(sig)
        if hit:
            print(f"  skip {sig} {d['kind']}/{d['asset']} (already present)")
            continue
        registry.register_rejection(d["kind"], d["params"], d["venue"], d["asset"],
                                    reason=d["reason"], metrics=d["metrics"], date=SEED_DATE)
        added += 1
        print(f"  +    {sig} {d['kind']}/{d['asset']}")
    print(f"[seed] registry now has {len(registry.list_rejections())} rejections (+{added})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
