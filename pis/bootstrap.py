"""Find the PIS page and make sure its fixed sub-structure exists (idempotent).

  PIS
  ├── 🧭 研究画像   (filled from config/profile.md on first run, then edited by you)
  ├── 🧠 记忆       (auto-maintained)
  ├── 📥 Inbox      (database: Name · URL · Note · Processed)
  ├── 📚 知识库     (database: one deep-dive page per paper / repo / tip / method / news item)
  └── 2026-10-31 …  (daily pages)

IDs can be overridden with NOTION_PIS_PAGE_ID / NOTION_PROFILE_PAGE_ID / NOTION_MEMORY_PAGE_ID / NOTION_INBOX_DB_ID.
"""
from __future__ import annotations

import os
from pathlib import Path

from .common import log
from .notion import Notion
from . import notion as N

PROFILE_TITLE, MEMORY_TITLE, INBOX_TITLE = "研究画像", "记忆", "Inbox"   # emoji lives in the page icon
LIBRARY_TITLE = "知识库"
LEGACY = {PROFILE_TITLE: ["🧭 研究画像"], MEMORY_TITLE: ["🧠 记忆"], INBOX_TITLE: ["📥 Inbox"],
          LIBRARY_TITLE: ["论文库", "📚 论文库"]}

ACCESS_HINT = ("无法访问 PIS 页面：请在 Notion 打开该页面 → 右上角 ··· → Connections（连接）→ 添加你的集成，"
               "并确认 GitHub Secret 中的 token 属于这个集成。")


def profile_blocks(md: str) -> list[dict]:
    blocks = []
    for line in md.splitlines():
        s = line.strip()
        if not s or s.startswith(">") or s.startswith("# "):
            continue
        if s.startswith("## "):
            blocks.append(N.heading(s[3:], 2))
        elif s.startswith("- "):
            blocks.append(N.bullet(N.rich(s[2:])))
        else:
            blocks.append(N.paragraph(N.rich(s)))
    return blocks


def find_pis(notion: Notion, cfg: dict) -> str:
    pid = os.environ.get("NOTION_PIS_PAGE_ID") or cfg.get("notion", {}).get("pis_page_id")
    if pid:
        return pid
    title = cfg.get("notion", {}).get("pis_page_title", "PIS")
    res = notion.req("POST", "/search", json={"query": title, "filter": {"property": "object", "value": "page"}})
    for p in res.get("results", []):
        t = "".join(x.get("plain_text", "") for x in p.get("properties", {}).get("title", {}).get("title", []))
        if t.startswith(title):
            return p["id"]
    raise RuntimeError(ACCESS_HINT)


def ensure(notion: Notion, cfg: dict, root: Path) -> dict[str, str]:
    pis = find_pis(notion, cfg)
    try:
        kids = notion.children(pis)
    except RuntimeError as e:
        raise RuntimeError(f"{ACCESS_HINT}\n{e}") from e
    pages = {b["child_page"]["title"]: b["id"] for b in kids if b["type"] == "child_page"}
    dbs = {b["child_database"]["title"]: b["id"] for b in kids if b["type"] == "child_database"}

    def existing(found: dict, title: str, kind: str) -> str | None:
        if title in found:
            return found[title]
        old = next((found[t] for t in LEGACY[title] if t in found), None)
        if old:   # created by an earlier version with the emoji duplicated in the title
            path, key = ("/pages/", "properties") if kind == "page" else ("/databases/", "title")
            text = [{"type": "text", "text": {"content": title}}]
            body = {"properties": {"title": {"title": text}}} if kind == "page" else {"title": text}
            try:
                notion.req("PATCH", path + old, json=body)
            except RuntimeError as e:
                log.warning("rename %s failed: %s", title, e)
        return old

    ids = {"pis": pis}
    ids["profile"] = os.environ.get("NOTION_PROFILE_PAGE_ID") or existing(pages, PROFILE_TITLE, "page") or notion.create_page(
        pis, PROFILE_TITLE,
        [N.callout(N.rich("这是你的长期研究画像。直接编辑本页即可，下次运行自动生效。写得越具体，筛选越准。"), "✏️")]
        + profile_blocks((root / "config" / "profile.md").read_text(encoding="utf-8")),
        emoji="🧭")
    ids["memory"] = os.environ.get("NOTION_MEMORY_PAGE_ID") or existing(pages, MEMORY_TITLE, "page") or notion.create_page(
        pis, MEMORY_TITLE,
        [N.callout(N.rich("PIS 每天运行后会在这里写入它对你近期兴趣的理解。"), "🧠", "purple_background")],
        emoji="🧠")
    ids["inbox"] = os.environ.get("NOTION_INBOX_DB_ID") or existing(dbs, INBOX_TITLE, "db") or notion.req("POST", "/databases", json={
        "parent": {"type": "page_id", "page_id": pis},
        "icon": {"type": "emoji", "emoji": "📥"},
        "title": [{"type": "text", "text": {"content": INBOX_TITLE}}],
        "properties": {"Name": {"title": {}}, "URL": {"url": {}}, "Note": {"rich_text": {}},
                       "Processed": {"checkbox": {}}},
    })["id"]
    try:   # columns used by instant processing (idempotent)
        notion.req("PATCH", f"/databases/{ids['inbox']}", json={"properties": {
            "日期": {"date": {}}, "类型": {"select": {}}, "摘要": {"rich_text": {}},
            "解析页": {"url": {}}, "已汇总": {"checkbox": {}}}})
    except RuntimeError as e:
        log.warning("adding Inbox columns failed: %s", e)
    lib_found = existing(dbs, LIBRARY_TITLE, "db")
    if lib_found:
        try:   # libraries created before the 类型 column existed
            notion.req("PATCH", f"/databases/{lib_found}", json={"properties": {"类型": {"select": {}}}})
        except RuntimeError as e:
            log.warning("adding 类型 column failed: %s", e)
    ids["library"] = lib_found or notion.req("POST", "/databases", json={
        "parent": {"type": "page_id", "page_id": pis},
        "icon": {"type": "emoji", "emoji": "📚"},
        "title": [{"type": "text", "text": {"content": LIBRARY_TITLE}}],
        "properties": {"Name": {"title": {}}, "URL": {"url": {}}, "日期": {"date": {}},
                       "来源": {"select": {}}, "类型": {"select": {}}, "相关度": {"number": {}},
                       "已读": {"checkbox": {}}},
    })["id"]
    log.info("Notion structure ready: %s", ids)
    return ids
