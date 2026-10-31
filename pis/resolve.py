"""Find the original paper behind a second-hand article (公众号 / 知乎 / blog).

DeepSeek's API cannot browse, so the work is split:
  1. the model reads the article and describes the paper (guessed English title, method name, authors,
     venue, keywords);
  2. we gather candidates from arXiv, Semantic Scholar and OpenReview with several queries;
  3. an exact title hit is accepted directly, otherwise the model compares each candidate's
     title + abstract with the article and picks the match (or none).
"""
from __future__ import annotations

import difflib
import os
import re
import threading
import time

import feedparser

from .common import Item, http_get, log
from .llm import LLM

IDENTIFY_SYSTEM = """下面是一篇介绍学术论文的中文文章。请找出它介绍的核心论文（只要一篇，选文章主要讲的那篇）。
只输出 JSON：
{"is_paper": true/false,
 "title": "论文的英文原标题。文章里写了就逐字照抄；没写就给出你认为最可能的英文标题",
 "title_given_in_article": true/false,
 "method_name": "论文提出的方法、模型或数据集的名字（英文，如 InfoTok），没有就留空",
 "authors": ["文章里提到的作者英文名或拼音，最多 5 个"],
 "institutions": ["机构英文名，最多 3 个"],
 "venue": "会议或期刊及年份，如 ICML 2026，不知道就留空",
 "keywords": ["4 到 6 个能在论文标题或摘要里出现的英文关键词"],
 "arxiv_id": "文章里出现的 arXiv 编号，没有就留空"}"""

VERIFY_SYSTEM = """给你一篇中文文章的内容，以及若干篇候选论文（标题和摘要）。判断哪一篇候选就是这篇文章介绍的那篇论文。
请比较研究问题、方法名、关键数字和实验设置、作者或机构。只有确定是同一篇时才选它，宁可不选也不要选错。
只输出 JSON：{"match": 候选编号（没有匹配就填 -1）, "confidence": 0 到 1 之间的数, "why": "不超过 30 字"}"""

_ID = re.compile(r"\d{4}\.\d{4,5}")


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _arxiv(query: str) -> list[dict]:
    try:
        r = http_get("https://export.arxiv.org/api/query", timeout=30, retries=2,
                     params={"search_query": query, "max_results": 8})
        if r.status_code != 200:
            return []
        out = []
        for e in feedparser.parse(r.content).entries:
            m = _ID.search(e.get("id", ""))
            if m:
                out.append({"title": re.sub(r"\s+", " ", e.get("title", "")).strip(), "arxiv_id": m.group(0),
                            "abstract": re.sub(r"\s+", " ", e.get("summary", "")).strip(), "source": "arXiv"})
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("arXiv search failed (%s): %s", query[:60], e)
        return []


_S2_LOCK = threading.Lock()
_S2_LAST = [0.0]
S2_INTERVAL = 1.5   # seconds between calls


def _s2_get(params: dict):
    """Semantic Scholar's shared anonymous quota is small: serialise calls across threads, back off on 429.
    Set S2_API_KEY (free from semanticscholar.org) for a dedicated quota."""
    headers = {"x-api-key": os.environ["S2_API_KEY"]} if os.environ.get("S2_API_KEY") else {}
    for attempt in range(6):
        with _S2_LOCK:
            wait = S2_INTERVAL - (time.time() - _S2_LAST[0])
            if wait > 0:
                time.sleep(wait)
            try:
                r = http_get("https://api.semanticscholar.org/graph/v1/paper/search", timeout=30, retries=1,
                             params=params, headers=headers)
            except RuntimeError as e:          # http_get raises on 429 / 5xx after its own retry
                if "429" not in str(e):
                    raise
                r = None
            _S2_LAST[0] = time.time()
        if r is not None and r.status_code != 429:
            return r
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("Semantic Scholar still rate-limited after 6 attempts")


def _s2(query: str) -> list[dict]:
    try:
        r = _s2_get({"query": query, "limit": 8, "fields": "title,abstract,externalIds,openAccessPdf,venue,year"})
        if r.status_code != 200:
            log.warning("Semantic Scholar search got HTTP %s (%s)", r.status_code, query[:60])
            return []
        out = []
        for p in r.json().get("data", []):
            out.append({"title": p.get("title") or "", "abstract": p.get("abstract") or "",
                        "arxiv_id": (p.get("externalIds") or {}).get("ArXiv"),
                        "pdf_url": (p.get("openAccessPdf") or {}).get("url"), "source": "Semantic Scholar"})
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("Semantic Scholar search failed (%s): %s", query[:60], e)
        return []


def _openreview(query: str) -> list[dict]:
    try:
        r = http_get("https://api2.openreview.net/notes/search", timeout=30, retries=2,
                     params={"term": query, "type": "terms", "content": "all", "source": "forum", "limit": 8})
        if r.status_code != 200:
            return []
        out = []
        for n in r.json().get("notes", []):
            c = n.get("content", {})
            val = lambda k: (c.get(k) or {}).get("value") if isinstance(c.get(k), dict) else c.get(k)  # noqa: E731
            if val("title"):
                out.append({"title": val("title"), "abstract": val("abstract") or "",
                            "pdf_url": f"https://openreview.net/pdf?id={n.get('forum') or n.get('id')}",
                            "source": "OpenReview"})
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("OpenReview search failed (%s): %s", query[:60], e)
        return []


def candidates(d: dict) -> list[dict]:
    title = (d.get("title") or "").strip()
    method = (d.get("method_name") or "").strip()
    kws = [k for k in d.get("keywords") or [] if k][:6]
    surname = ((d.get("authors") or [""])[0].split() or [""])[-1]
    words = _norm(title).split()

    queries_arxiv, queries_text = [], []
    if title:
        queries_arxiv += [f'ti:"{" ".join(words)}"', "all:" + " AND all:".join(words[:10])]
        queries_text.append(title)
    if method:
        queries_arxiv.append(f'ti:{_norm(method).replace(" ", " AND ti:")}')
        queries_text.append(" ".join([method] + kws[:3]))
    if kws:
        queries_arxiv.append("all:" + " AND all:".join(_norm(" ".join(kws[:4])).split()[:6]))
    if surname and (method or kws):
        queries_arxiv.append(f"au:{_norm(surname)} AND all:{_norm(method or kws[0]).split()[0]}")

    found: list[dict] = []
    for q in queries_arxiv:
        found += _arxiv(q)
    for q in queries_text:
        found += _s2(q) + _openreview(q)

    merged: dict[str, dict] = {}            # dedupe by normalised title, keep arXiv id / pdf from any source
    for c in found:
        k = _norm(c["title"])
        if not k:
            continue
        cur = merged.setdefault(k, dict(c))
        cur["arxiv_id"] = cur.get("arxiv_id") or c.get("arxiv_id")
        cur["pdf_url"] = cur.get("pdf_url") or c.get("pdf_url")
        if len(c.get("abstract") or "") > len(cur.get("abstract") or ""):
            cur["abstract"] = c["abstract"]
    return [c for c in merged.values() if c.get("arxiv_id") or c.get("pdf_url")]


def _result(c: dict) -> dict:
    return {"arxiv_id": c.get("arxiv_id"), "pdf_url": None if c.get("arxiv_id") else c.get("pdf_url"),
            "title": c["title"]}


def find_paper(llm: LLM, it: Item) -> dict | None:
    """-> {"arxiv_id" | "pdf_url", "title"} for the paper an article describes, or None."""
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

    cands = candidates(d)
    if not cands:
        log.warning("no candidate papers found for %s (guessed title: %s)", it.url, d.get("title"))
        return None
    best = max(cands, key=lambda c: similar(c["title"], d.get("title") or ""))
    if similar(best["title"], d.get("title") or "") >= 0.92:
        log.info("resolved %s -> %s (%s, exact title)", it.url, best["title"], best["source"])
        return _result(best)

    cands = sorted(cands, key=lambda c: -similar(c["title"], d.get("title") or ""))[:12]
    listing = "\n\n".join(f"[{i}] {c['title']}（{c['source']}）\n摘要：{(c.get('abstract') or '无')[:1200]}"
                          for i, c in enumerate(cands))
    try:
        v = llm.json(VERIFY_SYSTEM, f"# 中文文章\n标题：{it.title}\n{it.text[:8000]}\n\n# 候选论文\n{listing}",
                     temperature=0.0, max_tokens=1000)
        i, conf = int(v.get("match", -1)), float(v.get("confidence", 0))
    except Exception as e:  # noqa: BLE001
        log.warning("candidate verification failed for %s: %s", it.url, e)
        return None
    if 0 <= i < len(cands) and conf >= 0.7:
        log.info("resolved %s -> %s (%s, verified %.2f: %s)", it.url, cands[i]["title"], cands[i]["source"],
                 conf, v.get("why", ""))
        return _result(cands[i])
    log.warning("could not find the original paper for %s (guessed title: %s; %d candidates rejected)",
                it.url, d.get("title"), len(cands))
    return None
