import evolab.daemon as d
from evolab.store import Store


def _champ(asset, score):
    return {"asset": asset, "generation": 3, "new_champion": True,
            "champion": {"family": "rsi_reversion",
                         "params": {"rsi_n": 14, "lower": 30, "upper": 70},
                         "is_score": score}}


def test_maybe_publish_publishes_once_then_dedupes(tmp_path, monkeypatch):
    store = Store(tmp_path)
    calls = []
    monkeypatch.setattr(d, "publish_genome",
                        lambda asset, genome, base_url=None, api_key=None: calls.append((asset, genome.family)) or "rid")
    monkeypatch.setenv("EVOLAB_PUBLISH", "1")

    d.maybe_publish_champion(_champ("SOL", 1.5), store)
    d.maybe_publish_champion(_champ("SOL", 1.5), store)   # same champion -> deduped
    assert calls == [("SOL", "rsi_reversion")]

    d.maybe_publish_champion(_champ("SOL", 1.9), store)   # better champion -> publishes
    assert len(calls) == 2


def test_maybe_publish_disabled_by_env(tmp_path, monkeypatch):
    store = Store(tmp_path)
    calls = []
    monkeypatch.setattr(d, "publish_genome", lambda *a, **k: calls.append(1) or "rid")
    monkeypatch.setenv("EVOLAB_PUBLISH", "0")
    d.maybe_publish_champion(_champ("XRP", 2.0), store)
    assert calls == []


def test_maybe_publish_ignores_non_champion(tmp_path, monkeypatch):
    store = Store(tmp_path)
    calls = []
    monkeypatch.setattr(d, "publish_genome", lambda *a, **k: calls.append(1) or "rid")
    monkeypatch.setenv("EVOLAB_PUBLISH", "1")
    d.maybe_publish_champion({"asset": "SOL", "new_champion": False, "champion": None}, store)
    assert calls == []
