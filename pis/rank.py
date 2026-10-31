"""Relevance filtering: cheap keyword prefilter, then LLM scoring against the research profile."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from .common import Item, log
from .llm import LLM

_STOP = set("""the and for with from that this into over under using based about via are our their
these those than then also such more most very can will have has been being your you not use other
paper papers model models method methods learning large example""".split())


def profile_keywords(profile: str) -> set[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", profile)
    return {w.lower() for w in words if w.lower() not in _STOP}


def prefilter(items: list[Item], profile: str, limit: int) -> list[Item]:
    if len(items) <= limit:
        return items
    kws = profile_keywords(profile)

    def kscore(it: Item) -> float:
        t, a = it.title.lower(), it.text.lower()
        return sum(2 * (k in t) + (k in a) for k in kws) + min(it.upvotes, 50) / 5

    ranked = sorted(items, key=kscore, reverse=True)
    log.info("prefilter: %d -> %d by keywords", len(items), limit)
    return ranked[:limit]


SCORE_SYSTEM = """你是一名严格的科研信息筛选助手。根据用户的研究画像，判断每条信息对该用户的价值。
评分标准（0-10 的整数）：
- 9-10：直接命中核心兴趣，且有新意（新方法/重要结果/重要发布），用户一定想看
- 7-8：与核心兴趣明显相关，或是次要兴趣中的重要进展
- 5-6：有一定相关性，可看可不看
- 0-4：不相关、增量很小，或属于用户明确不感兴趣的方向
请克制，大多数条目应低于 6 分。
只输出 JSON：{"results": [{"id": <int>, "score": <int>, "why": "<不超过25字的中文理由>"}]}，必须覆盖所有 id。"""


def _score_batch(llm: LLM, profile: str, batch: list[tuple[int, Item]]) -> dict[int, tuple[float, str]]:
    lines = []
    for i, it in batch:
        extra = f" | HF赞:{it.upvotes}" if it.upvotes else ""
        lines.append(f"[{i}] ({it.origin}{extra}) {it.title}\n{it.text[:4000]}")
    user = f"# 研究画像\n{profile}\n\n# 待评分条目\n" + "\n\n".join(lines)
    try:
        d = llm.json(SCORE_SYSTEM, user, temperature=0.0, max_tokens=8000)
    except Exception as e:  # noqa: BLE001
        log.warning("scoring batch failed: %s", e)
        return {}
    out = {}
    for r in d.get("results", []):
        try:
            out[int(r["id"])] = (float(r.get("score", 0)), str(r.get("why", "")))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def score(llm: LLM, profile: str, items: list[Item], batch_size: int = 40, workers: int = 4) -> None:
    indexed = list(enumerate(items))
    batches = [indexed[i:i + batch_size] for i in range(0, len(indexed), batch_size)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(lambda b: _score_batch(llm, profile, b), batches):
            for i, (s, why) in res.items():
                if 0 <= i < len(items):
                    items[i].score, items[i].why = s, why
    log.info("scored %d items in %d batches", len(items), len(batches))


def select(items: list[Item], min_score: float, k: int) -> list[Item]:
    keep = [it for it in items if it.score >= min_score]
    keep.sort(key=lambda it: it.score + min(it.upvotes / 25, 1.5), reverse=True)
    return keep[:k]
