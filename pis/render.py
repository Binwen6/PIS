"""Render the digest into Notion blocks (main page + sub-pages) and Markdown (local copy)."""
from __future__ import annotations

from .common import Item
from . import notion as N

GROUPS = [
    ("papers", "📄 论文精选", lambda it: it.source in ("arxiv", "hf")),
    ("news",   "🌐 动态与博客", lambda it: it.source in ("blog", "social", "wechat")),
    ("inbox",  "📌 我的收藏", lambda it: it.source == "inbox"),
]


def _meta(it: Item) -> str:
    bits = [it.origin]
    if it.authors:
        a = it.authors.split(",")
        bits.append(", ".join(x.strip() for x in a[:3]) + (" 等" if len(a) > 3 else ""))
    if it.upvotes:
        bits.append(f"🔥 HF {it.upvotes}")
    if it.score and it.source != "inbox":
        bits.append(f"相关度 {it.score:.0f}/10")
    return " · ".join(b for b in bits if b)


def main_blocks(d: dict, links: dict[int, str], stats: str) -> list[dict]:
    blocks = [N.callout(N.rich(d.get("headline") or "今日摘要", bold=True), "📌", "blue_background")]
    if d.get("overview"):
        blocks.append(N.paragraph(N.rich_with_citations(d["overview"], links)))
    for th in d.get("themes", []):
        blocks.append(N.heading(th.get("title", ""), 3))
        blocks.append(N.paragraph(N.rich_with_citations(th.get("body", ""), links)))
    blocks.append(N.divider())
    blocks.append(N.paragraph(N.rich("各类条目详情见下方子页面；正文中的蓝色编号可直接点开原文。", color="gray")))
    blocks.append(N.paragraph(N.rich(stats, color="gray")))
    return blocks


def item_blocks(n: int, it: Item, d: dict) -> list[dict]:
    info = d.get("items_by_id", {}).get(n, {})
    kids = []
    if info.get("tldr"):
        kids.append(N.bullet(N.rich(info["tldr"])))
    if it.source == "inbox" and info.get("detail"):
        kids.append(N.bullet(N.rich(info["detail"])))
    if it.note:
        kids.append(N.bullet(N.rich("我的备注：" + it.note, color="brown")))
    if it.why:
        kids.append(N.bullet(N.rich("为什么推给你：" + it.why, color="gray")))
    if it.extra.get("hf_url"):
        kids.append(N.bullet(N.rich("Hugging Face 讨论页", link=it.extra["hf_url"])))
    head = N.rich(f"[{n}] ") + N.rich(it.title, link=it.url or None, bold=True) + N.rich("  " + _meta(it), color="gray")
    return [N.bullet(head, kids)]


def group_pages(numbered: list[tuple[int, Item]], d: dict) -> list[tuple[str, list[dict]]]:
    pages = []
    for _, title, pred in GROUPS:
        rows = [(n, it) for n, it in numbered if pred(it)]
        if not rows:
            continue
        blocks: list[dict] = []
        for n, it in rows:
            blocks += item_blocks(n, it, d)
        pages.append((f"{title}（{len(rows)}）", blocks))
    return pages


# ---- markdown (artifact / dry-run) ------------------------------------------
def _md_cite(text: str, links: dict[int, str]) -> str:
    def rep(m):
        nums = [s.strip() for s in m.group(1).replace("，", ",").split(",")]
        return "[" + ",".join(f"[{x}]({links[int(x)]})" if int(x) in links else x for x in nums) + "]"
    return N._CITE.sub(rep, text or "")


def markdown(date_title: str, d: dict, numbered: list[tuple[int, Item]], stats: str) -> str:
    links = {n: it.url for n, it in numbered}
    out = [f"# PIS · {date_title}", "", f"> **{d.get('headline', '')}**", ""]
    if d.get("overview"):
        out += [_md_cite(d["overview"], links), ""]
    for th in d.get("themes", []):
        out += [f"### {th.get('title', '')}", _md_cite(th.get("body", ""), links), ""]
    for _, title, pred in GROUPS:
        rows = [(n, it) for n, it in numbered if pred(it)]
        if not rows:
            continue
        out += [f"## {title}", ""]
        for n, it in rows:
            info = d.get("items_by_id", {}).get(n, {})
            out.append(f"- **[{n}] [{it.title}]({it.url})** — {_meta(it)}")
            for k in ("tldr", "detail"):
                if info.get(k):
                    out.append(f"  - {info[k]}")
            if it.why:
                out.append(f"  - _为什么推给你：{it.why}_")
        out.append("")
    out += ["---", stats]
    return "\n".join(out)
