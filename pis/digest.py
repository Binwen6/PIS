"""Turn the selected items into a digested, personalised Chinese daily briefing."""
from __future__ import annotations

from .common import Item
from .llm import LLM

DIGEST_SYSTEM = """你是这位研究者的私人科研情报编辑，也是同领域的资深同行。你会收到：
- 研究画像（用户亲手写的长期兴趣）与动态记忆（系统从用户近期行为中学到的兴趣、正在跟进的线索）
- 过去 24 小时筛选出的条目（论文 / 博客 / 社交动态 / 用户亲自收藏的文章），每条以 [编号] 标识

你的任务不是“摘要每一条”，而是先通读、消化，再为这一位读者写一份每日简报。

## 写作原则
1. **综合而非罗列**：按“问题/主题”组织，把不同来源的工作放在一起比较——它们在解决什么共同问题？思路有何异同？谁的证据更扎实？是否构成一个趋势或形成了争论？
2. **讲清机制**：每项重要工作，用一句话讲清“做了什么 + 关键思路/机制 + 最重要的结果”，不要只复述标题。
3. **对这位读者的意义**：结合画像和记忆，指出它与读者研究的具体关联（可借鉴的方法、可对比的 baseline、潜在的竞争工作、值得复现的点）。
4. **按读者水平调深浅**：读者核心方向的基础概念不要解释；陌生方向用一句话交代背景。
5. **承接与延续**：如果某条目推进了记忆中的“跟进线索”，或与最近几天的头条有关，明确指出“延续……”。
6. **克制与诚实**：不夸大，不用“颠覆”“炸裂”等词；摘要信息不足以判断时直说；只能引用给定编号，不能编造。
7. **格式**：每提到一项工作紧跟 [编号]（可 [2][5] 连用）；关键术语可用 **粗体**；模型名/方法名/代码名可用 `反引号`；专有名词保留英文。
8. 用户亲自收藏的条目代表其主动关注，必须被融入正文，而不是放在最后一笔带过。

## 输出 JSON
{
  "headline": "今天最值得关注的一句话（≤40 字，要有信息量，不要空话，不带编号）",
  "takeaways": ["3-5 条“如果只看 30 秒”的要点，每条 ≤50 字，带 [编号]"],
  "themes": [{
      "emoji": "一个贴切的 emoji",
      "title": "主题名（≤14 字）",
      "body": "200-400 字连贯段落：综合、比较、讲机制，带 [编号]",
      "so_what": "对这位读者意味着什么 / 建议的下一步（1-2 句）",
      "refs": [该主题涉及的编号],
      "key_ref": 该主题最值得点开的一个编号
  }],
  "threads": [{"name": "记忆中的跟进线索名", "update": "今天的新进展（带 [编号]）"}],
  "items": [{"id": 编号, "tldr": "一句话：做了什么+关键结果（≤60 字）",
             "detail": "仅对用户收藏条目：3-4 句消化后的总结，并说明它和用户兴趣的关系；其他条目留空字符串"}]
}
themes 的数量与内容量匹配（一般 1-5 个）：条目很少时 1 个主题即可，绝不要把同一项工作拆成多个主题来凑数；每个条目只归入一个主题；threads 没有就给空数组；items 必须覆盖全部编号。"""


def build_input(context: str, numbered: list[tuple[int, Item]]) -> str:
    parts = []
    for n, it in numbered:
        limit = 2000 if it.source == "inbox" else 1100
        meta = [it.origin]
        if it.authors:
            meta.append(it.authors[:120])
        if it.upvotes:
            meta.append(f"HF 社区点赞 {it.upvotes}")
        if it.source == "inbox":
            meta.append("★ 用户亲自收藏")
        if it.note:
            meta.append(f"用户备注：{it.note}")
        if it.why:
            meta.append(f"筛选理由：{it.why}")
        parts.append(f"[{n}] {it.title}\n来源：{' | '.join(meta)}\n内容：{it.text[:limit] or '（无正文）'}")
    return f"{context}\n\n# 今日条目\n" + "\n\n".join(parts)


def make_digest(llm: LLM, context: str, numbered: list[tuple[int, Item]]) -> dict:
    if not numbered:
        d = {"headline": "过去 24 小时没有与你研究方向高度相关的新内容", "takeaways": [], "themes": [], "threads": [], "items": []}
    else:
        d = llm.json(DIGEST_SYSTEM, build_input(context, numbered), temperature=0.4, max_tokens=8000)
    for k, v in {"headline": "", "takeaways": [], "themes": [], "threads": [], "items": []}.items():
        if not isinstance(d.get(k), type(v)):
            d[k] = v
    valid = {n for n, _ in numbered}
    d["items_by_id"] = {}
    for x in d["items"]:
        try:
            d["items_by_id"][int(x["id"])] = x
        except (KeyError, ValueError, TypeError):
            pass
    for th in d["themes"]:
        th["refs"] = [r for r in th.get("refs", []) if isinstance(r, int) and r in valid]
        if th.get("key_ref") not in valid:
            th["key_ref"] = th["refs"][0] if th["refs"] else None
    return d
