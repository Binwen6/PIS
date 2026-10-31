"""One-time Notion setup.

1. In Notion, create a page called「PIS」, then  ··· → Connections → add your integration.
2. NOTION_TOKEN=secret_xxx python setup_notion.py <PIS page URL or id>

Creates under PIS:  🧭 研究画像 (from config/profile.md) · 🧠 记忆 (auto-maintained) · 📥 Inbox (database),
and prints the IDs to put into GitHub Secrets.
"""
import re
import sys
from pathlib import Path

from pis import notion as N
from pis.notion import Notion


def page_id(arg: str) -> str:
    m = re.search(r"([0-9a-f]{32})", arg.replace("-", ""))
    if not m:
        sys.exit("cannot find a 32-char page id in: " + arg)
    h = m.group(1)
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def profile_blocks(md: str) -> list[dict]:
    blocks = []
    for line in md.splitlines():
        s = line.strip()
        if not s or s.startswith(">"):
            continue
        if s.startswith("## "):
            blocks.append(N.heading(s[3:], 2))
        elif s.startswith("# "):
            continue
        elif s.startswith("- "):
            blocks.append(N.bullet(N.rich(s[2:])))
        else:
            blocks.append(N.paragraph(N.rich(s)))
    return blocks


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    pis = page_id(sys.argv[1])
    n = Notion()
    md = (Path(__file__).parent / "config" / "profile.md").read_text(encoding="utf-8")
    prof = n.find_child_page(pis, "🧭 研究画像") or n.create_page(
        pis, "🧭 研究画像",
        [N.callout(N.rich("直接编辑本页即可更新研究兴趣，下次运行自动生效。"), "✏️")] + profile_blocks(md), emoji="🧭")
    mem = n.find_child_page(pis, "🧠 记忆") or n.create_page(
        pis, "🧠 记忆", [N.callout(N.rich("PIS 每天运行后会在这里写入它对你近期兴趣的理解。"), "🧠", "purple_background")],
        emoji="🧠")
    db = n.req("POST", "/databases", json={
        "parent": {"type": "page_id", "page_id": pis},
        "icon": {"type": "emoji", "emoji": "📥"},
        "title": [{"type": "text", "text": {"content": "📥 Inbox"}}],
        "properties": {
            "Name": {"title": {}},
            "URL": {"url": {}},
            "Note": {"rich_text": {}},
            "Processed": {"checkbox": {}},
        },
    })
    print("NOTION_PIS_PAGE_ID     =", pis)
    print("NOTION_PROFILE_PAGE_ID =", prof)
    print("NOTION_MEMORY_PAGE_ID  =", mem)
    print("NOTION_INBOX_DB_ID     =", db["id"])


if __name__ == "__main__":
    main()
