from evolab.store import Store, genome_to_dict
from evolab.genome import Genome


def test_seed_prepends_and_dedupes(tmp_path):
    store = Store(tmp_path)
    store.save_state("SOL", {"asset": "SOL", "generation": 5,
                             "population": [genome_to_dict(Genome("ma_cross", {"fast": 10, "slow": 50}))],
                             "champion": None})
    g = Genome("rsi_reversion", {"rsi_n": 14, "lower": 30, "upper": 70})

    store.seed_genome("SOL", g)
    pop = store.load_state("SOL")["population"]
    assert pop[0] == genome_to_dict(g)
    assert len(pop) == 2

    store.seed_genome("SOL", g)  # exact duplicate
    assert len(store.load_state("SOL")["population"]) == 2


def test_seed_creates_state_when_absent(tmp_path):
    store = Store(tmp_path)
    g = Genome("donchian_break", {"don": 30})
    store.seed_genome("XRP", g)
    state = store.load_state("XRP")
    assert state["population"][0] == genome_to_dict(g)
    assert state["asset"] == "XRP"
