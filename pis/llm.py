"""DeepSeek (OpenAI-compatible) chat client with JSON output."""
from __future__ import annotations

import json
import os
import time

import requests

from .common import log


class LLM:
    def __init__(self, base_url: str, model: str, api_key: str | None = None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = os.environ.get("DEEPSEEK_MODEL", model)
        self.key = api_key or os.environ["DEEPSEEK_API_KEY"]
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def json(self, system: str, user: str, *, temperature: float = 0.3, max_tokens: int = 8000) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        last: Exception | None = None
        for i in range(4):
            try:
                r = requests.post(self.url, json=body, timeout=300,
                                  headers={"Authorization": f"Bearer {self.key}"})
                if r.status_code in (429, 500, 502, 503):
                    raise RuntimeError(f"DeepSeek {r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                d = r.json()
                for k in self.usage:
                    self.usage[k] += d.get("usage", {}).get(k, 0)
                content = d["choices"][0]["message"]["content"]
                return json.loads(content)
            except (requests.RequestException, RuntimeError, json.JSONDecodeError, KeyError) as e:
                last = e
                log.warning("LLM call failed (attempt %d): %s", i + 1, e)
                time.sleep(3 * 2 ** i)
        raise RuntimeError(f"LLM failed after retries: {last}")
