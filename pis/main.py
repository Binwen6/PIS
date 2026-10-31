"""PIS daily run:  python -m pis.main [--dry-run] [--force] [--date YYYY-MM-DD]

Env:
  DEEPSEEK_API_KEY        required
  NOTION_TOKEN            required unless --dry-run
  DEEPSEEK_MODEL          optional model override
The PIS page comes from config/sources.yaml (notion.pis_page_id) or a title search; its sub-pages
(🧭 研究画像 / 🧠 记忆 / 📥 Inbox) are created automatically on the first run — see bootstrap.py.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .common import Item, log, utcnow
from .digest import make_digest
from .llm import LLM
from .notion import Notion
from . import bootstrap, memory, rank, render
from .sources import arxiv, feeds, hf_daily, notion_inbox

ROOT = Path(__file__).resolve().parent.parent


def load_profile(notion: Notion | None, pid: str | None) -> str:
    if notion and pid:
        try:
            txt = notion.page_text(pid)
            if len(txt) > 30:
                log.info("profile: loaded from Notion page")
                return txt
        except Exception as e:  # noqa: BLE001
            log.warning("profile from Notion failed, falling back to file: %s", e)
    return (ROOT / "config" / "profile.md").read_text(encoding="utf-8")


def gather(cfg: dict, notion: Notion | None, db: str | None, now: datetime,
           today: date) -> tuple[list[Item], list[Item], list[Item]]:
    papers: list[Item] = []
    if cfg.get("arxiv", {}).get("enabled", True):
        try:
            papers = arxiv.fetch(cfg["arxiv"])
        except Exception as e:  # noqa: BLE001
            log.error("arXiv failed: %s", e)
    if cfg.get("huggingface_daily", {}).get("enabled", True):
        papers = hf_daily.merge_into(papers, hf_daily.fetch(today))

    news = feeds.fetch(cfg.get("feeds", {}).get("list", []), now, cfg.get("window_hours", 26))

    inbox: list[Item] = []
    if notion and db and cfg.get("notion_inbox", {}).get("enabled", True):
        try:
            inbox = notion_inbox.fetch(notion, db)
        except Exception as e:  # noqa: BLE001
            log.error("Notion inbox failed: %s", e)
    return papers, news, inbox


def run(args) -> int:
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    tz = ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))
    now = utcnow()
    today = date.fromisoformat(args.date) if args.date else now.astimezone(tz).date()
    title = today.isoformat()

    notion = Notion() if os.environ.get("NOTION_TOKEN") else None
    if not args.dry_run and not notion:
        log.error("NOTION_TOKEN is not set (use --dry-run to only write Markdown)")
        return 2
    ids = bootstrap.ensure(notion, cfg, ROOT) if notion else {}
    parent = ids.get("pis", "")
    if not args.dry_run:
        existing = notion.find_child_page(parent, title)
        if existing and not args.force:
            log.info("page %s already exists, nothing to do (use --force to rebuild)", title)
            return 0
        if existing:
            notion.archive(existing)

    profile = load_profile(notion, ids.get("profile"))
    mem_page = ids.get("memory")
    mem = memory.load(notion, mem_page)
    ticked = memory.collect_feedback(notion, parent, today, mem) if mem_page else []
    context = f"# 研究画像（用户亲手写的长期兴趣）\n{profile}\n\n{memory.as_prompt(mem)}".strip()
    if ticked:
        context += "\n\n# 用户最近勾选想深读的条目\n" + "\n".join(f"- {t}" for t in ticked)

    llm = LLM(cfg["llm"]["base_url"], cfg["llm"]["model"], fallbacks=cfg["llm"].get("fallback_models", []))
    papers, news, inbox = gather(cfg, notion, ids.get("inbox"), now, today)

    acfg, fcfg, lcfg = cfg.get("arxiv", {}), cfg.get("feeds", {}), cfg["llm"]
    n_papers_raw = len(papers)
    papers = rank.prefilter(papers, context, acfg.get("prefilter_max", 800))
    rank.score(llm, context, papers + news, lcfg.get("score_batch_size", 40), lcfg.get("max_workers", 4))
    top_papers = rank.select(papers, acfg.get("min_score", 6), acfg.get("max_in_digest", 15))
    top_news = rank.select(news, fcfg.get("min_score", 6), fcfg.get("max_in_digest", 10))

    numbered = list(enumerate(top_papers + top_news + inbox, start=1))
    d = make_digest(llm, context, numbered)
    stats = (f"arXiv/HF 共 {n_papers_raw} 篇 → 精选 {len(top_papers)} 篇；动态 {len(news)} 条 → 精选 {len(top_news)} 条；"
             f"收藏 {len(inbox)} 条 · 模型 {llm.model} · tokens 入 {llm.usage['prompt_tokens']} / 出 {llm.usage['completion_tokens']}")

    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    md = render.markdown(title, d, numbered, stats)
    (out_dir / f"{title}.md").write_text(md, encoding="utf-8")
    log.info("markdown written to out/%s.md", title)

    if args.dry_run:
        print(md)
        return 0

    page_id = notion.create_page(parent, title, render.main_blocks(title, d, numbered, stats), emoji="📰")
    for sub_title, emoji, blocks in render.group_pages(numbered, d):
        notion.create_page(page_id, sub_title, blocks, emoji=emoji)
    notion_inbox.mark_processed(notion, inbox)

    if mem_page:   # learn from today's behaviour signals; failure here never loses the digest
        try:
            mem = memory.update(llm, profile, mem, today, inbox, ticked, d)
            notion.replace_content(mem_page, memory.blocks(mem, today))
            log.info("memory updated: %d interests, %d threads", len(mem["interests"]), len(mem["threads"]))
        except Exception as e:  # noqa: BLE001
            log.error("memory update failed: %s", e)
    log.info("Notion page created: https://www.notion.so/%s", page_id.replace("-", ""))
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="don't write to Notion, print Markdown")
    p.add_argument("--force", action="store_true", help="rebuild today's page if it exists")
    p.add_argument("--date", help="override page date (YYYY-MM-DD)")
    sys.exit(run(p.parse_args()))


if __name__ == "__main__":
    main()
