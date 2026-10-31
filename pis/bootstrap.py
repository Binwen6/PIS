"""Find the PIS page and make sure its fixed sub-structure exists (idempotent).

  PIS
  ├── 🧭 研究画像   (filled from config/profile.md on first run, then edited by you)
  ├── 🧠 记忆       (auto-maintained)
  ├── 📥 Inbox      (database: Name · URL · Note · Processed)
  └── 2026-10-31 …  (daily pages)

IDs can be overridden with NOTION_PIS_PAGE_ID / NOTION_PROFILE_PAGE_ID / NOTION_MEMORY_PAGE_ID / NOTION_INBOX_DB_ID.
"""
from __future__ import annotations

import os
from pathlib import Path

from .common import log
from .notion import Notion
from . import notion as N

PROFILE_TITLE, MEMORY_TITLE, INBOX_TITLE = "🧭 研究画像", "🧠 记忆", "📥 Inbox"

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

    ids = {"pis": pis}
    ids["profile"] = os.environ.get("NOTION_PROFILE_PAGE_ID") or pages.get(PROFILE_TITLE) or notion.create_page(
        pis, PROFILE_TITLE,
        [N.callout(N.rich("这是你的长期研究画像。直接编辑本页即可，下次运行自动生效。写得越具体，筛选越准。"), "✏️")]
        + profile_blocks((root / "config" / "profile.md").read_text(encoding="utf-8")),
        emoji="🧭")
    ids["memory"] = os.environ.get("NOTION_MEMORY_PAGE_ID") or pages.get(MEMORY_TITLE) or notion.create_page(
        pis, MEMORY_TITLE,
        [N.callout(N.rich("PIS 每天运行后会在这里写入它对你近期兴趣的理解。"), "🧠", "purple_background")],
        emoji="🧠")
    ids["inbox"] = os.environ.get("NOTION_INBOX_DB_ID") or dbs.get(INBOX_TITLE) or notion.req("POST", "/databases", json={
        "parent": {"type": "page_id", "page_id": pis},
        "icon": {"type": "emoji", "emoji": "📥"},
        "title": [{"type": "text", "text": {"content": INBOX_TITLE}}],
        "properties": {"Name": {"title": {}}, "URL": {"url": {}}, "Note": {"rich_text": {}},
                       "Processed": {"checkbox": {}}},
    })["id"]
    log.info("Notion structure ready: %s", ids)
    return ids
