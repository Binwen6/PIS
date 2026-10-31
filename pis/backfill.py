"""Backfill deep dives for specific items, without touching the rest of the daily page.

  python -m pis.backfill "https://arxiv.org/abs/2610.39302 https://mp.weixin.qq.com/s/xxx" [--date 2026-10-31]

Each target may be an arXiv link / id or any article link (公众号, 知乎, blog...). Articles are classified
like Inbox items (paper / repo / tip / ...) and get the matching template. Deep dives already in the
知识库 are reused, not regenerated. Links are appended to that day's page under「🔬 补充深度解析」.
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import date

import yaml

from .common import GitHubAnnotations, Item, log, utcnow
from .llm import LLM
from .notion import Notion
from .web import fetch_text
from . import bootstrap, classify, deepdive, notion as N
from .main import ROOT, load_profile

_BARE_ID = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")


def _inbox_note(notion: Notion, inbox: str | None, url: str) -> tuple[str, str | None]:
    """Your note on this link in the Inbox, if you saved it there."""
    if not inbox:
        return "", None
    try:
        for row in notion.query_db(inbox, {"property": "URL", "url": {"equals": url}}):
            props = row["properties"]
            if (props.get("URL", {}).get("url") or "") == url:
                note = "".join(t.get("plain_text", "") for t in props.get("Note", {}).get("rich_text", []))
                title = "".join(t.get("plain_text", "") for t in props.get("Name", {}).get("title", []))
                return note, (title if title and not title.startswith("http") else None)
    except Exception as e:  # noqa: BLE001
        log.warning("inbox lookup failed for %s: %s", url, e)
    return "", None


def to_item(token: str, notion: Notion, inbox: str | None) -> Item:
    token = token.strip()
    if _BARE_ID.match(token) or re.match(r"https?://(www\.)?arxiv\.org/", token):
        aid = deepdive.find_arxiv_id(token) or token.split("v")[0]
        return Item(source="arxiv", title=aid, url=f"https://arxiv.org/abs/{aid}", origin="arXiv",
                    extra={"arxiv_id": aid, "kind": "paper"})
    note, saved_title = _inbox_note(notion, inbox, token)
    title, text, img, aid, gh = fetch_text(token)
    return Item(source="inbox", title=saved_title or title or token, url=token, text=text, note=note,
                origin="微信公众号" if "mp.weixin.qq.com" in token else "我的收藏",
                extra={k: v for k, v in {"arxiv_id": aid, "github": gh}.items() if v})


def run(targets: list[str], day: date | None) -> int:
    cfg = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    from zoneinfo import ZoneInfo
    day = day or utcnow().astimezone(ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))).date()
    notion = Notion()
    ids = bootstrap.ensure(notion, cfg, ROOT)
    profile = load_profile(notion, ids.get("profile"))
    llm = LLM(cfg["llm"]["base_url"], cfg["llm"]["model"], fallbacks=cfg["llm"].get("fallback_models", []))

    items = [to_item(t, notion, ids.get("inbox")) for t in targets]
    classify.classify(llm, [it for it in items if it.source == "inbox"])
    dcfg = cfg.get("deep_dive", {})
    pages: list[str] = []
    for i, it in enumerate(items, start=1):
        res = deepdive.analyse(llm, notion, ids["library"], profile, i, it, day, dcfg)
        if res:
            pages.append(res[1])
        else:
            log.error("backfill failed for %s", it.url)

    day_page = notion.find_child_page(ids["pis"], day.isoformat())
    if day_page and pages:
        notion.append(day_page, [N.heading("🔬 补充深度解析", 2)] + [N.link_to_page(p) for p in pages])
        log.info("linked %d deep dives on %s", len(pages), day.isoformat())
    elif pages:
        log.warning("no daily page titled %s; deep dives are in 知识库 only", day.isoformat())
    return 0 if len(pages) == len(items) else 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        h = GitHubAnnotations(logging.WARNING)
        h.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        logging.getLogger().addHandler(h)
    p = argparse.ArgumentParser()
    p.add_argument("targets", nargs="+", help="arXiv links/ids or article links (one string may hold several)")
    p.add_argument("--date", help="daily page to link from (default: today)")
    a = p.parse_args()
    targets = [t for chunk in a.targets for t in re.split(r"[\s,，]+", chunk) if t]
    try:
        code = run(targets, date.fromisoformat(a.date) if a.date else None)
    except Exception:  # noqa: BLE001
        log.exception("backfill failed")
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
