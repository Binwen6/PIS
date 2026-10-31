"""Find the original paper behind a second-hand article (公众号 / 知乎 / blog).

DeepSeek's API cannot browse, so the work is split: the model reads the article and names the paper
(English title, authors, venue), then we look it up on arXiv and, failing that, Semantic Scholar
(which also knows OpenReview / proceedings PDFs). A candidate is accepted only if its title matches.
"""
from __future__ import annotations

import difflib
import re

import feedparser

from .common import Item, http_get, log
from .llm import LLM

IDENTIFY_SYSTEM = """下面是一篇介绍学术论文的中文文章。请找出它介绍的核心论文（只要一篇，选文章主要讲的那篇）。
只输出 JSON：
{"is_paper": true/false,
 "title": "论文的英文原标题。文章里写了就逐字照抄；没写就根据内容给出你认为最可能的英文标题",
 "title_given_in_article": true/false,
 "authors": ["文章里提到的作者英文名，最多 5 个"],
 "venue": "会议或期刊及年份，如 ICML 2026，不知道就留空",
 "arxiv_id": "文章里出现的 arXiv 编号，没有就留空"}"""

_ID = re.compile(r"\d{4}\.\d{4,5}")


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _arxiv_search(title: str) -> tuple[str, str] | None:
    words = _norm(title)
    if not words:
        return None
    for query in (f'ti:"{words}"', "all:" + " AND all:".join(words.split()[:12])):
        try:
            r = http_get("https://export.arxiv.org/api/query", timeout=30, retries=2,
                         params={"search_query": query, "max_results": 8})
            if r.status_code != 200:
                continue
            for e in feedparser.parse(r.content).entries:
                m = _ID.search(e.get("id", ""))
                if m and similar(e.get("title", ""), title) >= 0.88:
                    return m.group(0), re.sub(r"\s+", " ", e.title).strip()
        except Exception as e:  # noqa: BLE001
            log.warning("arXiv search failed: %s", e)
    return None


def _semantic_scholar(title: str) -> dict | None:
    try:
        r = http_get("https://api.semanticscholar.org/graph/v1/paper/search/match", timeout=30, retries=3,
                     params={"query": title, "fields": "title,externalIds,openAccessPdf,url,venue,year"})
        if r.status_code != 200:
            return None
        for p in r.json().get("data", []):
            if similar(p.get("title", ""), title) < 0.88:
                continue
            aid = (p.get("externalIds") or {}).get("ArXiv")
            pdf = (p.get("openAccessPdf") or {}).get("url")
            if aid or pdf:
                return {"arxiv_id": aid, "pdf_url": pdf, "title": p.get("title"), "page_url": p.get("url")}
    except Exception as e:  # noqa: BLE001
        log.warning("Semantic Scholar lookup failed: %s", e)
    return None


def find_paper(llm: LLM, it: Item) -> dict | None:
    """-> {"arxiv_id"?, "pdf_url"?, "title"} for the paper an article describes, or None."""
    try:
        d = llm.json(IDENTIFY_SYSTEM, f"标题：{it.title}\n\n{it.text[:30000]}", temperature=0.0, max_tokens=2000)
    except Exception as e:  # noqa: BLE001
        log.warning("paper identification failed for %s: %s", it.url, e)
        return None
    if not d.get("is_paper"):
        return None
    m = _ID.search(d.get("arxiv_id") or "")
    if m:
        return {"arxiv_id": m.group(0), "title": d.get("title")}
    title = (d.get("title") or "").strip()
    if not title:
        return None
    hit = _arxiv_search(title)
    if hit:
        log.info("resolved %s -> arXiv %s (%s)", it.url, hit[0], hit[1])
        return {"arxiv_id": hit[0], "title": hit[1]}
    s2 = _semantic_scholar(title)
    if s2:
        log.info("resolved %s -> Semantic Scholar %s", it.url, s2.get("title"))
        return s2
    log.warning("could not find the original paper for %s (guessed title: %s)", it.url, title)
    return None
