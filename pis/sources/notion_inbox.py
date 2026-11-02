"""Notion「📥 Inbox」database: links you saved by hand (公众号 / 小红书 / 知乎 / anything).

Properties: Name (title), URL (url), Note (rich_text), Processed (checkbox), plus the ones the instant
pipeline fills in: 日期 (date of the digest page it went to), 类型 (select), 摘要 (rich_text),
解析页 (url of the deep dive), 已汇总 (checkbox: already used by a morning digest).
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


def record_instant(notion: Notion, it: Item, day, kind_label: str, summary: str, deep_id: str | None) -> None:
    props = {
        "Processed": {"checkbox": True},
        "日期": {"date": {"start": day.isoformat()}},
        "类型": {"select": {"name": kind_label}},
        "摘要": {"rich_text": [{"text": {"content": (summary or "")[:1900]}}]},
    }
    if it.title and it.title != it.url:
        props["Name"] = {"title": [{"text": {"content": it.title[:200]}}]}
    if deep_id:
        props["解析页"] = {"url": f"https://www.notion.so/{deep_id.replace('-', '')}"}
    try:
        notion.update_props(it.notion_id, props)
    except Exception as e:  # noqa: BLE001
        log.warning("recording instant item %s failed: %s", it.url, e)


def fetch_instant(notion: Notion, db_id: str) -> list[Item]:
    """Items processed instantly but not yet part of a morning digest (context only, no refetch)."""
    from ..classify import KINDS
    by_label = {v[0]: k for k, v in KINDS.items()}
    try:
        rows = notion.query_db(db_id, {"and": [
            {"property": "Processed", "checkbox": {"equals": True}},
            {"property": "已汇总", "checkbox": {"equals": False}},
            {"property": "日期", "date": {"is_not_empty": True}},
        ]})
    except Exception as e:  # noqa: BLE001
        log.warning("instant items lookup failed: %s", e)
        return []
    items = []
    for row in rows:
        props = row["properties"]
        url = canonical_url(_plain(props.get("URL", {})))
        if not url:
            continue
        label = ((props.get("类型") or {}).get("select") or {}).get("name") or "其他"
        deep_url = _plain(props.get("解析页", {}))
        deep_id = deep_url.rstrip("/").split("/")[-1].split("-")[-1] if deep_url else ""
        origin = "微信公众号" if "mp.weixin.qq.com" in url else "我的收藏"
        items.append(Item(source="inbox", title=_plain(props.get("Name", {})) or url, url=url,
                          text=_plain(props.get("摘要", {})), note=_plain(props.get("Note", {})),
                          origin=f"{origin}（{label}）", notion_id=row["id"],
                          extra={k: v for k, v in {"kind": by_label.get(label, "other"), "instant": True,
                                                   "deep": deep_id}.items() if v}))
    log.info("Notion inbox: %d items already processed instantly", len(items))
    return items


def mark_digested(notion: Notion, items: list[Item]) -> None:
    for it in items:
        if it.notion_id:
            try:
                notion.update_props(it.notion_id, {"已汇总": {"checkbox": True}})
            except Exception as e:  # noqa: BLE001
                log.warning("mark digested failed for %s: %s", it.url, e)
