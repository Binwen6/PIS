"""arXiv daily announcements via the official RSS feed (rss.arxiv.org).

One request returns the whole day's announcement for the given categories, with abstracts,
so we don't have to page through the search API.
"""
from __future__ import annotations

import re

import feedparser

from ..common import Item, clean_html, http_get, log

_ABS_PREFIX = re.compile(r"^arXiv:\S+\s+Announce Type:\s*\S+\s*Abstract:\s*", re.I)


def parse_feed(content: bytes, include_cross: bool = True) -> list[Item]:
    feed = feedparser.parse(content)
    items: list[Item] = []
    for e in feed.entries:
        kind = (e.get("arxiv_announce_type") or "new").lower()
        allowed = {"new", "cross"} if include_cross else {"new"}
        if kind not in allowed:          # skip "replace" / "replace-cross" (revisions of old papers)
            continue
        link = e.get("link", "")
        m = re.search(r"(\d{4}\.\d{4,5})", link or e.get("id", ""))
        arxiv_id = m.group(1) if m else link
        abstract = _ABS_PREFIX.sub("", clean_html(e.get("summary", "")))
        cats = [t.get("term") for t in e.get("tags", []) if t.get("term")]
        items.append(Item(
            source="arxiv",
            title=clean_html(e.get("title", "")),
            url=f"https://arxiv.org/abs/{arxiv_id}",
            text=abstract,
            authors=clean_html(e.get("author", "")),
            origin="arXiv " + (cats[0] if cats else ""),
            key=f"arxiv:{arxiv_id}",
            extra={"categories": cats, "arxiv_id": arxiv_id},
        ))
    return items


def fetch(cfg: dict) -> list[Item]:
    cats = "+".join(cfg.get("categories", ["cs.CL"]))
    url = f"https://rss.arxiv.org/rss/{cats}"
    r = http_get(url)
    r.raise_for_status()
    items = parse_feed(r.content, cfg.get("include_cross_lists", True))
    # the combined feed can list one paper once per category -> dedupe
    seen, out = set(), []
    for it in items:
        if it.key not in seen:
            seen.add(it.key)
            out.append(it)
    log.info("arXiv: %d new papers in %s", len(out), cats)
    return out
