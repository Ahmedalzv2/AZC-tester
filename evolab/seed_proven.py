"""Seed the proven-universe populations with the playbook's known-good daily
trend genomes, so the best-15 board shows the real edge immediately — before any
daemon evolution. Idempotent: dedups against whatever's already in each
population. Donchian breakout is THE proven family (playbook §1/§2); the grid
spans the long-trend regime (don 50-80, the schema's deep end) × ATR stop ×
chandelier trail × regime gate on/off.
"""
from __future__ import annotations

from evolab.genome import Genome
from evolab.store import genome_to_dict
from evolab.universe import PROVEN

DONS = (50, 65, 80)          # schema caps don at 80; long-trend breakouts
ATR_MULTS = (2.0, 3.0)
TRAILS = (3, 5)              # chandelier
ER_MINS = (0.0, 0.3)        # ungated vs regime-gated (schema choices)


def seed_genomes() -> list[Genome]:
    out = []
    for don in DONS:
        for atr in ATR_MULTS:
            for trail in TRAILS:
                for er in ER_MINS:
                    out.append(Genome("donchian_break", {
                        "don": don, "atrN": 14, "atrMult": atr,
                        "trail": trail, "erMin": er, "regimeN": 20}))
    return out


def main() -> int:
    store = PROVEN.store()
    genomes = seed_genomes()
    assets = PROVEN.assets()
    if not assets:
        print("[seed] no proven fixtures found — run scripts/fetch_proven_fixtures.py first")
        return 1
    for asset in assets:
        state = store.load_state(asset)
        pop = state.get("population", [])
        seen = {(g["family"], tuple(sorted(g["params"].items()))) for g in pop}
        added = 0
        for g in genomes:
            gd = genome_to_dict(g)
            key = (gd["family"], tuple(sorted(gd["params"].items())))
            if key not in seen:
                pop.append(gd)
                seen.add(key)
                added += 1
        state["asset"] = asset
        state["population"] = pop
        store.save_state(asset, state)
        print(f"  {asset:<6} +{added:<2} (pop {len(pop)})")
    print(f"[seed] {len(genomes)} genomes across {len(assets)} proven assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
