"""Process Inbox links right after you save them (the iOS shortcut triggers the inbox workflow).

  python -m pis.instant

For every unprocessed Inbox link: fetch, classify, find the original paper, write the deep dive,
and append it to the page of the *next* digest:
  - today's page if this morning's digest has not been written yet,
  - otherwise tomorrow's page (created now as a skeleton).
The morning run later inserts the digest above a placeholder and only uses these items as context.
"""
from __future__ import annotations

import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import yaml

from .common import GitHubAnnotations, Item, log, utcnow
from .llm import LLM
from .notion import Notion
from .style import WRITING_STYLE, sanitize_obj
from .sources import notion_inbox
from . import bootstrap, classify, deepdive, notion as N, render
from .main import ROOT, load_profile

PLACEHOLDER = "☀️ 今日简报（arXiv 新论文与综合摘要）会在早上自动生成，放在这里。"
SECTION = "📌 即时收藏"

SUMMARY_SYSTEM = """你会收到用户刚收藏的几篇内容（带类型和用户备注）以及用户的研究画像。为每篇写：
- tldr：一句话说清它是什么，以及最重要的结论或用途（不超过 60 字）
- detail：3 到 4 句消化后的总结。论文讲问题、方法和关键结果；工具讲用途和上手方式；技巧讲具体做法；资讯讲事实和影响。最后一句说明它和用户研究的关系。
只输出 JSON：{"items": [{"id": 编号, "tldr": "...", "detail": "..."}]}

""" + WRITING_STYLE


def is_skeleton(notion: Notion, page_id: str) -> str | None:
    """-> id of the placeholder block if the page still waits for its morning digest."""
    for b in notion.children(page_id)[:3]:
        if b["type"] == "callout":
            text = "".join(t.get("plain_text", "") for t in b["callout"]["rich_text"])
            if text.startswith(PLACEHOLDER[:6]):
                return b["id"]
    return None


def target_page(notion: Notion, pis: str, today: date) -> tuple[date, str]:
    page = notion.find_child_page(pis, today.isoformat())
    day = today
    if page and not is_skeleton(notion, page):        # this morning's digest is out -> next one
        day = today + timedelta(days=1)
        page = notion.find_child_page(pis, day.isoformat())
    if not page:
        page = notion.create_page(pis, day.isoformat(), [
            N.callout(N.rich(PLACEHOLDER), "☀️", "yellow_background"),
            N.divider(),
            N.heading(SECTION, 2),
        ], emoji="📰")
        log.info("created page %s for instant items", day.isoformat())
    return day, page


def summarize(llm: LLM, profile: str, items: list[Item]) -> dict[int, dict]:
    lines = [f"[{i}] {it.title}（{classify.label(it)}）\n" + (f"用户备注：{it.note}\n" if it.note else "") +
             f"正文：{it.text[:12000]}" for i, it in enumerate(items)]
    try:
        d = sanitize_obj(llm.json(SUMMARY_SYSTEM, f"# 研究画像\n{profile[:3000]}\n\n# 新收藏\n" + "\n\n".join(lines),
                                  temperature=0.3, max_tokens=8000))
        return {int(x["id"]): x for x in d.get("items", []) if "id" in x}
    except Exception as e:  # noqa: BLE001
        log.warning("instant summaries failed: %s", e)
        return {}


def item_blocks(it: Item, info: dict, deep_id: str | None) -> list[dict]:
    kids = []
    if info.get("tldr"):
        kids.append(N.paragraph(N.rich(info["tldr"], bold=True)))
    if info.get("detail"):
        kids.append(N.paragraph(N.rich(info["detail"])))
    if it.note:
        kids.append(N.quote(N.rich("我的备注：" + it.note), color="brown"))
    if deep_id:
        kids.append(N.link_to_page(deep_id))
    head = N.rich(it.title, link=it.url or None, bold=True) + N.rich("  " + render._meta(it), color="gray")
    return [N.todo(head, kids)]


def run() -> int:
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    today = utcnow().astimezone(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date()
    notion = Notion()
    ids = bootstrap.ensure(notion, cfg, ROOT)
    items = notion_inbox.fetch(notion, ids["inbox"])
    if not items:
        log.info("no new Inbox links")
        return 0
    profile = load_profile(notion, ids.get("profile"))
    llm = LLM(cfg["llm"]["base_url"], cfg["llm"]["model"], fallbacks=cfg["llm"].get("fallback_models", []))
    classify.classify(llm, items)
    day, page = target_page(notion, ids["pis"], today)

    dcfg = cfg.get("deep_dive", {})
    with ThreadPoolExecutor(max_workers=dcfg.get("workers", 5)) as ex:
        deep = list(ex.map(lambda x: deepdive.analyse(llm, notion, ids["library"], profile, x[0], x[1], day, dcfg),
                           enumerate(items, start=1)))
    summaries = summarize(llm, profile, items)

    blocks: list[dict] = []
    for i, (it, d) in enumerate(zip(items, deep)):
        blocks += item_blocks(it, summaries.get(i, {}), d[1] if d else None)
    notion.append(page, blocks)
    for i, (it, d) in enumerate(zip(items, deep)):
        info = summaries.get(i, {})
        notion_inbox.record_instant(notion, it, day, classify.label(it),
                                    " ".join(x for x in (info.get("tldr"), info.get("detail")) if x),
                                    d[1] if d else None)
    log.info("instant: %d items -> page %s (%d deep dives)", len(items), day.isoformat(), sum(1 for d in deep if d))
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        h = GitHubAnnotations(logging.WARNING)
        h.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logging.getLogger().addHandler(h)
    try:
        code = run()
    except Exception:  # noqa: BLE001
        log.exception("instant processing failed")
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
