"""DeepSeek (OpenAI-compatible) chat client with JSON output."""
from __future__ import annotations

import json
import os
import time

import requests

from .common import log


class LLM:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, fallbacks: list[str] | None = None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = os.environ.get("DEEPSEEK_MODEL") or model
        self.fallbacks = [m for m in (fallbacks or []) if m != self.model]
        self.key = api_key or os.environ["DEEPSEEK_API_KEY"]
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def json(self, system: str, user: str, *, temperature: float = 0.3, max_tokens: int = 8000,
             retries: int = 4) -> dict:
        return self._chat(system, user, temperature, max_tokens, as_json=True, retries=retries)

    def text(self, system: str, user: str, *, temperature: float = 0.5, max_tokens: int = 8000) -> str:
        return self._chat(system, user, temperature, max_tokens, as_json=False)

    def _chat(self, system: str, user: str, temperature: float, max_tokens: int, as_json: bool, retries: int = 4):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if as_json:
            body["response_format"] = {"type": "json_object"}
        last: Exception | None = None
        for i in range(retries):
            try:
                r = requests.post(self.url, json=body, timeout=300,
                                  headers={"Authorization": f"Bearer {self.key}"})
                if r.status_code in (400, 404) and "model" in r.text.lower() and self.fallbacks:
                    log.warning("model %s rejected (%s); falling back to %s", self.model, r.text[:120], self.fallbacks[0])
                    self.model = body["model"] = self.fallbacks.pop(0)
                    continue
                if r.status_code in (429, 500, 502, 503):
                    raise RuntimeError(f"DeepSeek {r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                d = r.json()
                for k in self.usage:
                    self.usage[k] += d.get("usage", {}).get(k, 0)
                choice = d["choices"][0]
                content = choice["message"].get("content") or ""
                finish = choice.get("finish_reason")
                if not as_json:
                    if len(content.strip()) < 200:
                        raise RuntimeError(f"empty completion (finish_reason={finish})")
                    if finish == "length":
                        log.warning("completion hit max_tokens (%d chars); keeping what we have", len(content))
                    return content
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"bad JSON ({e}); finish_reason={finish}, {len(content)} chars, "
                                       f"usage={d.get('usage')}") from e
            except (requests.RequestException, RuntimeError, json.JSONDecodeError, KeyError) as e:
                last = e
                log.warning("LLM call failed (attempt %d): %s", i + 1, e)
                time.sleep(3 * 2 ** i)
        raise RuntimeError(f"LLM failed after retries: {last}")
