"""Hugging Face Daily Papers — a community-curated popularity signal."""
from __future__ import annotations

from datetime import date, timedelta

from ..common import Item, http_get, log


def fetch(today: date) -> list[Item]:
    items: dict[str, Item] = {}
    for d in (today - timedelta(days=1), today):
        try:
            r = http_get(f"https://huggingface.co/api/daily_papers?date={d.isoformat()}")
            if r.status_code != 200:
                continue
            for row in r.json():
                p = row.get("paper", {})
                pid = p.get("id")
                if not pid:
                    continue
                items[pid] = Item(
                    source="hf",
                    title=(p.get("title") or row.get("title") or "").strip(),
                    url=f"https://huggingface.co/papers/{pid}",
                    text=(p.get("summary") or "").strip(),
                    authors=", ".join(a.get("name", "") for a in p.get("authors", [])[:8]),
                    origin="HF Daily Papers",
                    upvotes=int(p.get("upvotes") or 0),
                    key=f"arxiv:{pid}",
                    extra={"arxiv_id": pid},
                )
        except Exception as e:  # noqa: BLE001 - a failed source must not kill the run
            log.warning("HF daily papers %s failed: %s", d, e)
    log.info("HF Daily Papers: %d papers", len(items))
    return list(items.values())


def merge_into(arxiv_items: list[Item], hf_items: list[Item]) -> list[Item]:
    """Attach HF upvotes to arXiv papers; add HF-only papers (e.g. older but trending)."""
    by_key = {it.key: it for it in arxiv_items}
    for h in hf_items:
        if h.key in by_key:
            by_key[h.key].upvotes = h.upvotes
            by_key[h.key].extra["hf_url"] = h.url
        else:
            h.source = "arxiv"
            h.url = f"https://arxiv.org/abs/{h.extra['arxiv_id']}"
            h.extra["hf_url"] = f"https://huggingface.co/papers/{h.extra['arxiv_id']}"
            arxiv_items.append(h)
    return arxiv_items
