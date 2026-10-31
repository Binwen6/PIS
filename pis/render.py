"""Render the digest into Notion blocks (main page + sub-pages) and Markdown (local copy).

Main page layout
  📌 headline callout · ⏱ 30 秒速览 callout · 目录
  ## <emoji> 主题 ×N   (paragraph with clickable [n] · 💬 对你的意义 quote · bookmark card of the key item)
  ## 🧵 线索追踪      (progress on threads remembered from earlier days)
  ▸ 🗺 今日图谱       (Mermaid diagram: themes → items)
  ▸ 📋 全部条目一览   (table)
Sub-pages: 📄 论文精选 / 🌐 动态与博客 / 📌 我的收藏 — each item is a ☐ to-do; ticking it feeds 🧠 记忆.
"""
from __future__ import annotations

from .common import Item
from . import notion as N

GROUPS = [
    ("papers", "📄 论文精选", lambda it: it.source in ("arxiv", "hf")),
    ("news",   "🌐 动态与博客", lambda it: it.source in ("blog", "social", "wechat")),
    ("inbox",  "📌 我的收藏", lambda it: it.source == "inbox"),
]


def _meta(it: Item, with_score: bool = True) -> str:
    bits = [it.origin]
    if it.authors:
        a = it.authors.split(",")
        bits.append(", ".join(x.strip() for x in a[:3]) + (" 等" if len(a) > 3 else ""))
    if it.upvotes:
        bits.append(f"🔥 HF {it.upvotes}")
    if with_score and it.score and it.source != "inbox":
        bits.append(f"相关度 {it.score:.0f}/10")
    return " · ".join(b for b in bits if b)


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def mermaid(date_title: str, d: dict, items: dict[int, Item]) -> str:
    def lbl(s: str) -> str:
        return s.replace('"', "'").replace("\n", " ")
    lines = ["graph LR", f'  D(("{date_title}"))']
    for i, th in enumerate(d.get("themes", [])):
        lines.append(f'  D --> T{i}["{lbl(th.get("emoji", "") + " " + th.get("title", ""))}"]')
        for r in th.get("refs", []):
            if r in items:
                lines.append(f'  T{i} --> I{r}["[{r}] {lbl(_short(items[r].title, 30))}"]')
    return "\n".join(lines)


def main_blocks(date_title: str, d: dict, numbered: list[tuple[int, Item]], stats: str,
                deep: dict[int, str] | None = None) -> list[dict]:
    deep = deep or {}
    items = dict(numbered)
    links = {n: it.url for n, it in numbered}
    cite = lambda t, **kw: N.rich_with_citations(t, links, **kw)  # noqa: E731

    blocks = [N.callout([{**t, "annotations": {**t.get("annotations", {}), "bold": True}}
                         for t in cite(d.get("headline") or "今日简报")], "📌", "blue_background")]
    if d.get("takeaways"):
        c = N.callout(N.rich("30 秒速览", bold=True), "⏱", "yellow_background")
        c["callout"]["children"] = [N.bullet(cite(t)) for t in d["takeaways"]]
        blocks.append(c)
    if len(d.get("themes", [])) > 1:
        blocks.append(N.toc())

    bookmarked: set[int] = set()
    for th in d.get("themes", []):
        blocks.append(N.heading(f"{th.get('emoji', '')} {th.get('title', '')}".strip(), 2))
        blocks.append(N.paragraph(cite(th.get("body", ""))))
        blocks += [N.link_to_page(deep[r]) for r in th.get("refs", []) if r in deep]
        if th.get("so_what"):
            blocks.append(N.quote(N.rich("💬 对你：", bold=True) + cite(th["so_what"]), color="brown"))
        key = items.get(th.get("key_ref"))
        if key and th["key_ref"] not in bookmarked:
            bookmarked.add(th["key_ref"])
            blocks.append(N.bookmark(key.extra.get("hf_url") or key.url))

    if d.get("threads"):
        blocks.append(N.heading("🧵 线索追踪", 2))
        blocks += [N.bullet(N.rich(t.get("name", "") + "：", bold=True) + cite(t.get("update", "")))
                   for t in d["threads"]]

    if d.get("themes"):
        blocks.append(N.toggle(N.rich("🗺 今日图谱", bold=True), [N.code(mermaid(date_title, d, items), "mermaid")]))
    if numbered:
        rows = [[N.rich(str(n)), N.rich(_short(it.title, 90), link=it.url or None), N.rich(it.origin),
                 N.rich(f"{it.score:.0f}" if it.score and it.source != "inbox" else "★")] for n, it in numbered]
        blocks.append(N.toggle(N.rich("📋 全部条目一览", bold=True), [N.table(["#", "标题", "来源", "相关度"], rows)]))

    blocks.append(N.divider())
    blocks.append(N.callout(N.rich("在下方子页面中 ☑ 勾选你想深读的条目，PIS 会据此更新「🧠 记忆」，推送会越来越懂你。"),
                            "🎯", "gray_background"))
    blocks.append(N.paragraph(N.rich(stats, color="gray")))
    return blocks


def item_blocks(n: int, it: Item, d: dict, deep: dict[int, str] | None = None) -> list[dict]:
    info = d.get("items_by_id", {}).get(n, {})
    kids = []
    if deep and n in deep:
        kids.append(N.link_to_page(deep[n]))
    if info.get("tldr"):
        kids.append(N.paragraph(N.rich(info["tldr"])))
    if info.get("detail"):
        kids.append(N.paragraph(N.rich(info["detail"])))
    if it.note:
        kids.append(N.quote(N.rich("我的备注：" + it.note), color="brown"))
    if it.extra.get("image"):
        kids.append(N.image(it.extra["image"]))
    if it.why:
        kids.append(N.paragraph(N.rich("为什么推给你：" + it.why, color="gray", italic=True)))
    if it.extra.get("hf_url"):
        kids.append(N.paragraph(N.rich("↗ Hugging Face 讨论页", link=it.extra["hf_url"], color="gray")))
    head = N.rich(f"[{n}] ") + N.rich(it.title, link=it.url or None, bold=True) + N.rich("  " + _meta(it), color="gray")
    return [N.todo(head, kids)]


def group_pages(numbered: list[tuple[int, Item]], d: dict,
                deep: dict[int, str] | None = None) -> list[tuple[str, str, list[dict]]]:
    pages = []
    for _, title, pred in GROUPS:
        rows = [(n, it) for n, it in numbered if pred(it)]
        if not rows:
            continue
        blocks: list[dict] = [N.callout(N.rich("☑ 勾选 = 想深读 / 感兴趣，这会成为你的兴趣信号。"), "🎯", "gray_background")]
        for n, it in rows:
            blocks += item_blocks(n, it, d, deep)
        emoji, name = title.split(" ", 1)
        pages.append((f"{name}（{len(rows)}）", emoji, blocks))
    return pages


# ---- markdown (local copy / dry-run) -----------------------------------------
def _md(text: str, links: dict[int, str]) -> str:
    def rep(m):
        nums = [s.strip() for s in m.group(1).replace("，", ",").split(",")]
        return "[" + ",".join(f"[{x}]({links[int(x)]})" if int(x) in links else x for x in nums) + "]"
    return N._CITE.sub(rep, text or "")


def markdown(date_title: str, d: dict, numbered: list[tuple[int, Item]], stats: str) -> str:
    links = {n: it.url for n, it in numbered}
    out = [f"# PIS · {date_title}", "", f"> 📌 **{d.get('headline', '')}**", ""]
    if d.get("takeaways"):
        out += ["**⏱ 30 秒速览**", ""] + [f"- {_md(t, links)}" for t in d["takeaways"]] + [""]
    for th in d.get("themes", []):
        out += [f"## {th.get('emoji', '')} {th.get('title', '')}", "", _md(th.get("body", ""), links), ""]
        if th.get("so_what"):
            out += [f"> 💬 **对你：** {_md(th['so_what'], links)}", ""]
    if d.get("threads"):
        out += ["## 🧵 线索追踪", ""] + [f"- **{t.get('name')}**：{_md(t.get('update', ''), links)}" for t in d["threads"]] + [""]
    for _, title, pred in GROUPS:
        rows = [(n, it) for n, it in numbered if pred(it)]
        if not rows:
            continue
        out += [f"## {title}", ""]
        for n, it in rows:
            info = d.get("items_by_id", {}).get(n, {})
            out.append(f"- [ ] **[{n}] [{it.title}]({it.url})** — {_meta(it)}")
            for k in ("tldr", "detail"):
                if info.get(k):
                    out.append(f"  - {info[k]}")
            if it.why:
                out.append(f"  - _为什么推给你：{it.why}_")
        out.append("")
    out += ["---", stats]
    return "\n".join(out)
