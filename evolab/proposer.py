"""LLM strategy proposer — EvoLab Phase 3.

When the genetic search stalls, ask an LLM to propose fresh genomes (a signal
family + params) given the genome schema and the best recently-tried genomes
with their fitness. Proposals are *coerced to legal genomes* (`genome.coerce`)
and seeded into the population — they then go through the exact same
`fitness.evaluate` gate (fee-accurate OOS + cumulative Bonferroni deflation) as
every other genome. The LLM only widens where the search looks; it cannot lower
the honest significance bar.

Provider-agnostic: any OpenAI-compatible /chat/completions endpoint (OpenRouter,
DeepSeek, OpenAI, a local llama.cpp server, ...) via env, using only stdlib
urllib (no new dependency):

    EVOLAB_LLM_API_KEY   required to enable the proposer at all
    EVOLAB_LLM_BASE_URL  default https://openrouter.ai/api/v1
    EVOLAB_LLM_MODEL     default deepseek/deepseek-chat

No key set -> client_from_env() returns None -> the search runs as a pure GA,
exactly as before. Every failure path (no key, network error, garbage output)
degrades to "propose nothing", never an exception into the search loop.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from evolab.genome import PARAM_SCHEMAS, Genome, coerce, genome_key

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "deepseek/deepseek-chat"
_TIMEOUT_S = 60


def schema_text() -> str:
    """Compact, prompt-friendly rendering of every legal family + its knobs."""
    lines = []
    for family, schema in PARAM_SCHEMAS.items():
        parts = []
        for name, spec in schema.items():
            if spec.kind == "choice":
                parts.append(f"{name}: one of {list(spec.choices)}")
            else:
                parts.append(f"{name}: {spec.kind} in [{spec.low}..{spec.high}] step {spec.step}")
        lines.append(f"- {family}: " + "; ".join(parts))
    return "\n".join(lines)


def build_messages(recent: list[dict], champion: dict | None, n: int) -> list[dict]:
    """System+user chat messages asking for `n` new genomes as strict JSON."""
    system = (
        "You are a quantitative strategy search assistant for a fee-accurate "
        "crypto backtester. You propose strategy configurations (genomes) for an "
        "evolutionary search that has stalled. Every proposal is validated and "
        "backtested out-of-sample with real taker fees, so only genuinely "
        "different, plausible ideas help — do not just echo the examples.\n\n"
        "Legal signal families and their parameter ranges:\n" + schema_text() + "\n\n"
        "Reply with ONLY a JSON object of the form "
        '{"genomes": [{"family": "<one of the families>", "params": {<all params for that family>}}]}. '
        "Every param listed for a family is required and must be within its range. "
        "No prose, no markdown fences."
    )
    recent_txt = json.dumps(recent, default=str) if recent else "(none yet)"
    champ_txt = json.dumps(champion, default=str) if champion else "(none found yet)"
    user = (
        f"The search has stalled. Best recently-tried genomes (with in-sample mean "
        f"netR and out-of-sample t-stat):\n{recent_txt}\n\n"
        f"Current champion (survived the OOS gate), if any:\n{champ_txt}\n\n"
        f"Propose {n} new, diverse genomes likely to find an edge these missed. "
        f"Vary families and parameters meaningfully. Return JSON only."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def _load_json(text: str) -> Any:
    """Best-effort: whole string, else the widest {...}/[...] slice. None on fail."""
    t = _strip_fences(text)
    try:
        return json.loads(t)
    except (json.JSONDecodeError, TypeError):
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = t.find(open_c), t.rfind(close_c)
        if 0 <= i < j:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


def parse_proposals(text: str) -> list[Genome]:
    """Extract legal, deduped genomes from raw LLM text. Tolerates code fences,
    surrounding prose, a bare array or a {"genomes": [...]} wrapper. Illegal,
    unknown-family, or incomplete entries are silently dropped."""
    obj = _load_json(text)
    if isinstance(obj, dict):
        obj = obj.get("genomes", [])
    if not isinstance(obj, list):
        return []
    out: list[Genome] = []
    seen: set = set()
    for item in obj:
        if not isinstance(item, dict):
            continue
        g = coerce(item.get("family", ""), item.get("params", {}) or {})
        if g is None:
            continue
        k = genome_key(g)
        if k not in seen:
            seen.add(k)
            out.append(g)
    return out


def _extract_text(resp: Any) -> str:
    try:
        return resp["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


class OpenAICompatibleClient:
    """Minimal OpenAI-compatible chat-completions client (stdlib only)."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _build_payload(self, messages: list[dict]) -> dict:
        # Some temperature for proposal diversity; the OOS gate filters the rest.
        return {"model": self.model, "messages": messages, "temperature": 0.8}

    def complete(self, messages: list[dict]) -> str:
        data = json.dumps(self._build_payload(messages)).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=data, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as r:
            return _extract_text(json.loads(r.read().decode()))


def client_from_env() -> OpenAICompatibleClient | None:
    """Build a client from EVOLAB_LLM_* env, or None if no API key is set
    (offline => pure GA, the proposer is simply skipped)."""
    key = os.environ.get("EVOLAB_LLM_API_KEY")
    if not key:
        return None
    return OpenAICompatibleClient(
        api_key=key,
        base_url=os.environ.get("EVOLAB_LLM_BASE_URL", _DEFAULT_BASE_URL),
        model=os.environ.get("EVOLAB_LLM_MODEL", _DEFAULT_MODEL),
    )


def propose(client, recent: list[dict], champion: dict | None, n: int) -> list[Genome]:
    """Ask the client for up to `n` legal genomes. Returns [] for no client,
    n<=0, any network/parse error — never raises into the search loop."""
    if client is None or n <= 0:
        return []
    try:
        text = client.complete(build_messages(recent, champion, n))
    except Exception:
        return []
    return parse_proposals(text)[:n]
