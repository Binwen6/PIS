"""Shared types and helpers."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape

import requests

log = logging.getLogger("pis")

UA = {"User-Agent": "Mozilla/5.0 (PIS personal digest bot; +https://github.com)"}


@dataclass
class Item:
    source: str            # arxiv / hf / blog / social / wechat / inbox
    title: str
    url: str
    text: str = ""         # abstract / summary / extracted article text
    authors: str = ""
    origin: str = ""       # human readable source name, e.g. "arXiv cs.CL", "OpenAI News"
    published: datetime | None = None
    upvotes: int = 0       # HF Daily Papers popularity
    note: str = ""         # user's own note (inbox)
    key: str = ""          # dedupe key (arXiv id / url)
    notion_id: str = ""    # inbox row id, to mark processed
    score: float = 0.0
    why: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.key:
            self.key = self.url


def clean_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def http_get(url: str, *, timeout: int = 60, retries: int = 3, **kw) -> requests.Response:
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, timeout=timeout, headers={**UA, **kw.pop("headers", {})}, **kw)
            if r.status_code < 500 and r.status_code != 429:
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {url}")
        except requests.RequestException as e:  # network hiccup
            last = e
        time.sleep(2 ** (i + 1))
    raise last  # type: ignore[misc]


class GitHubAnnotations(logging.Handler):
    """In GitHub Actions, surface warnings/errors as run annotations (readable via the REST API)."""

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if record.exc_info:
            import traceback
            msg += "\n" + "".join(traceback.format_exception(*record.exc_info))[-6000:]
        msg = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        level = "error" if record.levelno >= logging.ERROR else "warning"
        print(f"::{level}::{msg}", flush=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
