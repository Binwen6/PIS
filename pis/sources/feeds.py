"""Generic RSS / Atom feeds: blogs, RSSHub routes (X, 知乎, 小红书), wewe-rss (公众号)."""
from __future__ import annotations

from calendar import timegm
from datetime import datetime, timedelta, timezone

import feedparser

from ..common import Item, clean_html, http_get, log


def _published(e) -> datetime | None:
    for k in ("published_parsed", "updated_parsed"):
        t = e.get(k)
        if t:
            return datetime.fromtimestamp(timegm(t), tz=timezone.utc)
    return None


def fetch(feed_list: list[dict], now: datetime, window_hours: int) -> list[Item]:
    since = now - timedelta(hours=window_hours)
    out: list[Item] = []
    seen: set[str] = set()
    for f in feed_list:
        try:
            r = http_get(f["url"], timeout=30)
            r.raise_for_status()
            parsed = feedparser.parse(r.content)
        except Exception as e:  # noqa: BLE001
            log.warning("feed %s failed: %s", f.get("name"), e)
            continue
        n = 0
        for e in parsed.entries:
            pub = _published(e)
            link = e.get("link", "")
            if pub is None or pub < since or link in seen:
                continue
            seen.add(link)
            body = ""
            if e.get("content"):
                body = e.content[0].get("value", "")
            body = clean_html(body or e.get("summary", ""))[:3000]
            out.append(Item(
                source=f.get("kind", "blog"),
                title=clean_html(e.get("title", "")) or "(无标题)",
                url=link,
                text=body,
                authors=clean_html(e.get("author", "")),
                origin=f.get("name", ""),
                published=pub,
            ))
            n += 1
        log.info("feed %s: %d new", f.get("name"), n)
    return out
