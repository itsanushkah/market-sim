"""Single entry point for every LLM call in the project.

Features
- Backends: "anthropic" (Claude API), "ollama" (free local open models, e.g. qwen2.5:3b),
  or "mock" (deterministic heuristic, free; used for tests and dry runs).
- Structured JSON output via output_config.format (json_schema), so agents always get parseable actions.
- Disk cache keyed on the full request: re-running a seed costs nothing and gives identical results.
- Usage accounting (calls, tokens, estimated $) per agent, written to results/<exp>/<seed>/llm_usage.json.
- Refusals and errors never crash a run: the call returns None and the agent falls back to "pass".
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# $ per 1M tokens (input, output). Update if pricing changes.
PRICING = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.00, 50.00),
}
# Server-side refusal fallback is supported on these models (not Haiku).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"}


def parse_json_lenient(text: str, schema: dict) -> dict | None:
    """Parse model JSON; if output was cut off by the token cap inside a trailing string field (usually
    "reasoning"), close it and keep the answer, provided every required field is present."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    required = schema.get("required", [])
    for suffix in ('"}', '}', '""}'):
        try:
            out = json.loads(text.rstrip() + suffix)
        except json.JSONDecodeError:
            continue
        if all(k in out for k in required):
            out["_truncated"] = True
            return out
    return None


@dataclass
class LLMSettings:
    backend: str = "mock"            # "anthropic" | "ollama" | "mock"
    model: str = "claude-opus-5-5"
    effort: str = "low"              # low | medium | high | xhigh | max
    max_tokens: int = 4000
    cache_dir: str = ".llm_cache"
    use_cache: bool = True

    @classmethod
    def from_dict(cls, d: dict | None) -> "LLMSettings":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Usage:
    calls: int = 0
    cache_hits: int = 0
    failures: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    by_agent: dict = field(default_factory=lambda: defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0}))

    def to_dict(self) -> dict:
        return {"calls": self.calls, "cache_hits": self.cache_hits, "failures": self.failures,
                "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cost_usd": round(self.cost_usd, 4), "by_agent": dict(self.by_agent)}


class LLMClient:
    def __init__(self, settings: LLMSettings):
        self.s = settings
        self.usage = Usage()
        self._lock = threading.Lock()
        self._client = None
        if settings.backend == "anthropic":
            import anthropic
            self._anthropic = anthropic
            self._client = anthropic.Anthropic(max_retries=4)
        self.cache_path = Path(settings.cache_dir)
        if settings.use_cache:
            self.cache_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def complete_json(self, *, agent_id: str, system: str, user: str, schema: dict,
                      mock_fn: Callable[[], dict]) -> dict | None:
        """Return a dict matching `schema`, or None on refusal/error.

        `mock_fn` is the deterministic policy used when backend == "mock".
        """
        with self._lock:
            self.usage.calls += 1
            self.usage.by_agent[agent_id]["calls"] += 1

        if self.s.backend == "mock":
            return mock_fn()

        key = self._key(system, user, schema)
        cached = self._cache_get(key)
        if cached is not None:
            with self._lock:
                self.usage.cache_hits += 1
            return cached

        if self.s.backend == "ollama":
            result, in_tok, out_tok = self._call_ollama(system, user, schema)
        else:
            result, in_tok, out_tok = self._call_anthropic(system, user, schema)
        with self._lock:
            self.usage.input_tokens += in_tok
            self.usage.output_tokens += out_tok
            self.usage.by_agent[agent_id]["input_tokens"] += in_tok
            self.usage.by_agent[agent_id]["output_tokens"] += out_tok
            pin, pout = PRICING.get(self.s.model, (0.0, 0.0))
            self.usage.cost_usd += in_tok / 1e6 * pin + out_tok / 1e6 * pout
            if result is None:
                self.usage.failures += 1
        if result is not None:
            self._cache_put(key, result)
        return result

    # ------------------------------------------------------------------
    def _call_anthropic(self, system: str, user: str, schema: dict) -> tuple[dict | None, int, int]:
        a = self._anthropic
        kwargs = dict(
            model=self.s.model,
            max_tokens=self.s.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.s.effort,
                           "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            if self.s.model in FALLBACK_MODELS:
                # Server-side fallback: if a safety classifier declines, the API retries on another model.
                resp = self._client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            else:
                resp = self._client.messages.create(**kwargs)
        except a.BadRequestError as e:
            print(f"[llm] bad request: {e.message}")
            return None, 0, 0
        except (a.AuthenticationError, a.PermissionDeniedError) as e:
            raise RuntimeError("Claude API credentials missing or invalid. Set ANTHROPIC_API_KEY "
                               "or run `ant auth login`, or use --backend mock.") from e
        except a.RateLimitError:
            print("[llm] rate limited after retries; agent will pass this turn")
            return None, 0, 0
        except a.APIStatusError as e:
            print(f"[llm] API error {e.status_code}: {e.message}")
            return None, 0, 0
        except a.APIConnectionError:
            print("[llm] connection error; agent will pass this turn")
            return None, 0, 0

        in_tok, out_tok = resp.usage.input_tokens, resp.usage.output_tokens
        if resp.stop_reason in ("refusal", "max_tokens"):
            return None, in_tok, out_tok
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            return None, in_tok, out_tok
        try:
            return json.loads(text), in_tok, out_tok
        except json.JSONDecodeError:
            return None, in_tok, out_tok

    def _call_ollama(self, system: str, user: str, schema: dict) -> tuple[dict | None, int, int]:
        """Local model via Ollama's /api/chat. `format` = JSON schema constrains the output (Ollama >= 0.5)."""
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not host.startswith("http"):
            host = "http://" + host
        body = json.dumps({
            "model": self.s.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            # Short outputs keep a laptop run tractable; the JSON action needs well under 150 tokens.
            "options": {"temperature": 0.7, "num_predict": min(self.s.max_tokens, 200), "num_ctx": 2048},
            "keep_alive": "30m",
        }).encode()
        req = urllib.request.Request(f"{host}/api/chat", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                resp = json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")
            if e.code == 404:
                raise RuntimeError(f"Ollama model {self.s.model!r} not found. Run: ollama pull {self.s.model}") from e
            print(f"[llm] ollama error {e.code}: {msg[:200]}")
            return None, 0, 0
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError(f"Cannot reach Ollama at {host}. Is the Ollama app running?") from e
        in_tok, out_tok = resp.get("prompt_eval_count", 0), resp.get("eval_count", 0)
        return parse_json_lenient(resp.get("message", {}).get("content", ""), schema), in_tok, out_tok

    # --- cache --------------------------------------------------------
    def _key(self, system: str, user: str, schema: dict) -> str:
        blob = json.dumps([self.s.model, self.s.effort, system, user, schema], sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _cache_get(self, key: str) -> dict | None:
        if not self.s.use_cache:
            return None
        p = self.cache_path / f"{key}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def _cache_put(self, key: str, value: dict) -> None:
        if self.s.use_cache:
            (self.cache_path / f"{key}.json").write_text(json.dumps(value))
