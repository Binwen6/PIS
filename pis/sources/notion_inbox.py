"""Notion「📥 Inbox」database: links you saved by hand (公众号 / 小红书 / 知乎 / anything).

Expected properties (created by setup_notion.py):
  Name (title) · URL (url) · Note (rich_text) · Processed (checkbox)
"""
from __future__ import annotations

from ..common import Item, log
from ..notion import Notion
from ..web import canonical_url, fetch_text


def _plain(prop: dict) -> str:
    if not prop:
        return ""
    t = prop.get("type")
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in prop[t])
    if t == "url":
        return prop.get("url") or ""
    return ""


def fetch(notion: Notion, db_id: str) -> list[Item]:
    rows = notion.query_db(db_id, {"property": "Processed", "checkbox": {"equals": False}})
    items = []
    for row in rows:
        props = row["properties"]
        name = _plain(next((p for p in props.values() if p["type"] == "title"), {}))
        url = canonical_url(_plain(props.get("URL", {})) or (name if name.startswith("http") else ""))
        note = _plain(props.get("Note", {}))
        if not url:
            continue
        title, text, img, aid, gh = fetch_text(url)
        items.append(Item(
            source="inbox",
            title=(name if name and not name.startswith("http") else title) or url,
            url=url,
            text=text,
            note=note,
            origin="微信公众号" if "mp.weixin.qq.com" in url else "我的收藏",
            notion_id=row["id"],
            extra={k: v for k, v in {"image": img, "arxiv_id": aid, "github": gh}.items() if v},
        ))
    log.info("Notion inbox: %d unprocessed links", len(items))
    return items


def mark_processed(notion: Notion, items: list[Item]) -> None:
    for it in items:
        if it.notion_id:
            props = {"Processed": {"checkbox": True}}
            if it.title and it.title != it.url:
                props["Name"] = {"title": [{"text": {"content": it.title[:200]}}]}
            try:
                notion.update_props(it.notion_id, props)
            except Exception as e:  # noqa: BLE001
                log.warning("mark processed failed for %s: %s", it.url, e)
