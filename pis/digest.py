"""Turn the selected items into a condensed, coherent Chinese daily digest."""
from __future__ import annotations

from .common import Item
from .llm import LLM

DIGEST_SYSTEM = """你是用户的私人科研情报编辑。你会收到用户的研究画像，以及过去 24 小时内筛选出的若干条目（论文、博客、社交媒体动态、用户自己收藏的文章），每条以 [编号] 标识。

请写一份高度浓缩的每日摘要，要求：
1. 用精炼、连贯的中文自然语言，像一位懂行的同事在早会上做简报，而不是逐条罗列。
2. 按“主题”而不是按来源组织：把相关的工作串起来，指出它们的共同趋势、分歧或互补之处，以及与用户研究的关联。
3. 每提到一项工作，紧跟着用 [编号] 标注出处（可以 [2][5] 连用）。只能引用给定的编号，不要编造。
4. 专有名词、方法名、模型名保留英文原文。不要夸大，不确定的地方如实说明。
5. 用户收藏的条目（来源为“我的收藏/微信公众号”）代表用户主动关注，需要在摘要中体现。

只输出 JSON：
{
  "headline": "今天最值得关注的一句话（不超过 40 字）",
  "overview": "3-5 句今日总览，带 [编号]",
  "themes": [{"title": "主题名（≤12 字）", "body": "150-300 字的连贯段落，带 [编号]"}],
  "items": [{"id": <int>, "tldr": "一句话要点（≤60 字）", "detail": "仅对用户收藏条目给出 3-4 句总结，其他留空"}]
}
themes 一般 2-5 个；items 必须覆盖所有编号。"""


def build_input(profile: str, numbered: list[tuple[int, Item]]) -> str:
    parts = []
    for n, it in numbered:
        limit = 1800 if it.source == "inbox" else 1000
        meta = [it.origin]
        if it.authors:
            meta.append(it.authors[:120])
        if it.upvotes:
            meta.append(f"HF赞 {it.upvotes}")
        if it.note:
            meta.append(f"用户备注：{it.note}")
        parts.append(f"[{n}] {it.title}\n来源：{' | '.join(meta)}\n内容：{it.text[:limit] or '（无正文）'}")
    return f"# 研究画像\n{profile}\n\n# 今日条目\n" + "\n\n".join(parts)


def make_digest(llm: LLM, profile: str, numbered: list[tuple[int, Item]]) -> dict:
    if not numbered:
        return {"headline": "过去 24 小时没有与你研究方向高度相关的新内容", "overview": "", "themes": [], "items": []}
    d = llm.json(DIGEST_SYSTEM, build_input(profile, numbered), temperature=0.4, max_tokens=8000)
    d.setdefault("headline", "")
    d.setdefault("overview", "")
    d.setdefault("themes", [])
    d["items_by_id"] = {}
    for x in d.get("items", []):
        try:
            d["items_by_id"][int(x["id"])] = x
        except (KeyError, ValueError, TypeError):
            pass
    return d
