from evolab.genome import Genome
from evolab.publish import _assemble_payload, build_run_payload


def _verdict(kind, t=2.3, p=0.01, n=45, mean=0.015):
    return {"verdict": kind, "family": "rsi_reversion", "net_R_oos": 0.7,
            "is": {"n": 50, "meanR": 0.02, "t": 2.5},
            "oos": {"n": n, "meanR": mean, "t": t, "p": p, "holds": kind == "real"}}


def test_assemble_payload_shape_and_tags():
    g = Genome("rsi_reversion", {"rsi_n": 14, "lower": 30, "upper": 70})
    trades = [
        {"ts": 1, "dir": "long", "netR": 0.5, "win": True},
        {"ts": 2, "dir": "long", "netR": 0.5, "win": True},
        {"ts": 3, "dir": "long", "netR": 0.5, "win": True},
        {"ts": 4, "dir": "long", "netR": -0.5, "win": False},
    ]
    req, resp = _assemble_payload("SOL", g, trades, _verdict("real"))

    assert req["strategy"] == "evolab:rsi_reversion"
    assert req["data_provider"] == "azc_fixture"
    assert req["symbol"] == "SOL"
    assert req["interval"] == "4h"
    assert req["strategy_params"] == g.params

    m = resp["metrics"]
    assert m["trade_count"] == 4
    assert m["win_rate_pct"] == 75.0
    assert m["total_r"] == 1.0
    assert "total_return_pct" in m and "max_drawdown_pct" in m and "sharpe" in m
    assert m["fee_model"] == "all-taker"

    s = resp["significance"]
    assert s["significant"] is True
    assert s["verdict"] == "real"
    assert s["scope"] == "oos"
    assert s["n"] == 45
    assert s["tstat"] == 2.3
    assert resp["evolab"]["family"] == "rsi_reversion"


def test_assemble_payload_noise_is_not_significant():
    g = Genome("ma_cross", {"fast": 10, "slow": 50})
    req, resp = _assemble_payload("XRP", g, [], _verdict("noise", t=0.4, p=0.6, n=10, mean=-0.01))
    assert resp["metrics"]["trade_count"] == 0
    assert resp["significance"]["significant"] is False
    assert resp["significance"]["verdict"] == "noise"


def test_build_run_payload_runs_a_real_family(monkeypatch):
    from engine_bracket import Bar
    import evolab.publish as pub

    bars = []
    px = 100.0
    for i in range(200):
        px *= 1.012 if i % 6 else 0.985
        bars.append(Bar(t=i, o=px, h=px * 1.01, l=px * 0.99, c=px))
    monkeypatch.setattr(pub.data, "load_asset", lambda asset: bars)
    monkeypatch.setattr(pub.data, "split", lambda b, oos_fraction=0.30: (b[:140], b[140:]))

    req, resp = pub.build_run_payload("SOL", Genome("donchian_break", {"don": 20}))
    assert req["symbol"] == "SOL"
    assert req["strategy"] == "evolab:donchian_break"
    assert "trade_count" in resp["metrics"]
    assert resp["significance"]["scope"] == "oos"
    assert "verdict" in resp["significance"]


def test_post_ingest_sends_payload(monkeypatch):
    import io
    import evolab.publish as pub
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        captured["key"] = req.headers.get("X-api-key")

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R(b'{"run_id": "abc123"}')

    import json
    monkeypatch.setattr(pub.urllib.request, "urlopen", fake_urlopen)
    rid = pub.post_ingest({"symbol": "SOL"}, {"metrics": {}}, base_url="http://x:3016", api_key="secret")
    assert rid == "abc123"
    assert captured["url"].endswith("/api/runs/ingest")
    assert captured["body"]["request_payload"]["symbol"] == "SOL"
    assert captured["key"] == "secret"
