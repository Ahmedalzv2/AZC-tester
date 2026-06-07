from __future__ import annotations

from pathlib import Path
import json
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from evolab import proposer
from evolab.genome import Genome, coerce

# A fully-legal donchian_break param set (matches PARAM_SCHEMAS grid).
LEGAL_DB = {"don": 30, "atrN": 14, "atrMult": 2.0, "trail": 3, "erMin": 0.0, "regimeN": 20}


# ── genome.coerce — turn arbitrary LLM family+params into a legal genome ──────
def test_coerce_returns_legal_genome():
    g = coerce("donchian_break", dict(LEGAL_DB))
    assert isinstance(g, Genome) and g.family == "donchian_break"
    assert g.params["don"] == 30


def test_coerce_clamps_out_of_range_to_grid():
    g = coerce("donchian_break", {**LEGAL_DB, "don": 999})
    assert g.params["don"] == 80  # clamped to schema max


def test_coerce_unknown_family_is_none():
    assert coerce("nope", LEGAL_DB) is None


def test_coerce_missing_param_is_none():
    assert coerce("donchian_break", {"don": 30}) is None


def test_coerce_repairs_cross_param_constraint():
    g = coerce("ma_cross", {"fast": 50, "slow": 50, "atrN": 14, "atrMult": 2.0, "trail": 3})
    assert g.params["fast"] < g.params["slow"]


def test_coerce_ignores_extra_keys():
    g = coerce("donchian_break", {**LEGAL_DB, "bogus": 123})
    assert "bogus" not in g.params


# ── parse_proposals — robustly extract legal genomes from raw LLM text ────────
def test_parse_proposals_plain_array():
    text = json.dumps([{"family": "donchian_break", "params": LEGAL_DB}])
    out = proposer.parse_proposals(text)
    assert len(out) == 1 and out[0].family == "donchian_break"


def test_parse_proposals_genomes_object():
    text = json.dumps({"genomes": [{"family": "donchian_break", "params": LEGAL_DB}]})
    assert len(proposer.parse_proposals(text)) == 1


def test_parse_proposals_strips_code_fence():
    inner = json.dumps({"genomes": [{"family": "donchian_break", "params": LEGAL_DB}]})
    assert len(proposer.parse_proposals(f"```json\n{inner}\n```")) == 1


def test_parse_proposals_clamps_and_skips_unknown():
    text = json.dumps([
        {"family": "donchian_break", "params": {**LEGAL_DB, "don": 999}},
        {"family": "unknownfam", "params": {}},
    ])
    out = proposer.parse_proposals(text)
    assert len(out) == 1 and out[0].params["don"] == 80


def test_parse_proposals_dedups():
    text = json.dumps([
        {"family": "donchian_break", "params": LEGAL_DB},
        {"family": "donchian_break", "params": LEGAL_DB},
    ])
    assert len(proposer.parse_proposals(text)) == 1


def test_parse_proposals_garbage_is_empty():
    assert proposer.parse_proposals("not json at all") == []


def test_parse_proposals_skips_incomplete_params():
    text = json.dumps([{"family": "donchian_break", "params": {"don": 30}}])
    assert proposer.parse_proposals(text) == []


# ── prompt + payload + response plumbing ─────────────────────────────────────
def test_schema_text_lists_all_families():
    s = proposer.schema_text()
    for fam in ("donchian_break", "ma_cross", "rsi_reversion"):
        assert fam in s


def test_build_messages_has_system_and_user():
    msgs = proposer.build_messages(recent=[], champion=None, n=3)
    roles = [m["role"] for m in msgs]
    assert "system" in roles and "user" in roles
    blob = " ".join(m["content"] for m in msgs)
    assert "donchian_break" in blob and "JSON" in blob


def test_openai_payload_shape():
    c = proposer.OpenAICompatibleClient(api_key="k", base_url="http://x/v1", model="m")
    p = c._build_payload([{"role": "user", "content": "hi"}])
    assert p["model"] == "m" and p["messages"][0]["content"] == "hi"


def test_extract_text_from_response():
    assert proposer._extract_text({"choices": [{"message": {"content": "hello"}}]}) == "hello"


def test_extract_text_malformed_is_empty():
    assert proposer._extract_text({"oops": 1}) == ""


# ── client_from_env — offline (no key) must yield None, never crash ──────────
def test_client_from_env_none_without_key(monkeypatch):
    monkeypatch.delenv("EVOLAB_LLM_API_KEY", raising=False)
    assert proposer.client_from_env() is None


def test_client_from_env_builds_with_key(monkeypatch):
    monkeypatch.setenv("EVOLAB_LLM_API_KEY", "secret")
    monkeypatch.setenv("EVOLAB_LLM_MODEL", "my-model")
    c = proposer.client_from_env()
    assert c is not None and c.model == "my-model"


def test_default_base_is_direct_provider_not_openrouter(monkeypatch):
    monkeypatch.setenv("EVOLAB_LLM_API_KEY", "secret")
    monkeypatch.delenv("EVOLAB_LLM_BASE_URL", raising=False)
    c = proposer.client_from_env()
    assert "openrouter" not in c.base_url
    assert c.base_url == "https://api.openai.com/v1"


# ── propose — orchestration, never raises into the search loop ────────────────
class _FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        return self.text


def test_propose_returns_legal_genomes():
    text = json.dumps({"genomes": [{"family": "donchian_break", "params": LEGAL_DB}]})
    out = proposer.propose(_FakeClient(text), recent=[], champion=None, n=2)
    assert len(out) == 1 and isinstance(out[0], Genome)


def test_propose_none_client_is_empty():
    assert proposer.propose(None, recent=[], champion=None, n=2) == []


def test_propose_swallows_client_error():
    class Boom:
        def complete(self, m):
            raise RuntimeError("network down")
    assert proposer.propose(Boom(), recent=[], champion=None, n=2) == []


def test_propose_respects_n_limit():
    genomes = [{"family": "donchian_break", "params": {**LEGAL_DB, "don": d}}
               for d in (10, 15, 20, 25, 30)]
    out = proposer.propose(_FakeClient(json.dumps({"genomes": genomes})),
                           recent=[], champion=None, n=2)
    assert len(out) == 2
