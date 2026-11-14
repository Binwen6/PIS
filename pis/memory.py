"""Dynamic interest memory.

Two layers of personalisation:
  🧭 研究画像  — explicit, stable, written by you (Notion page / config/profile.md)
  🧠 记忆      — implicit, dynamic, maintained by PIS from your behaviour:
                 · links you put into 📥 Inbox (+ your notes)          strong signal
                 · items you tick ☑ in previous daily pages            strong signal
                 · themes of recent digests                            weak signal / continuity
The memory lives on a Notion page: a readable summary + a JSON code block (the source of truth).
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from .common import Item, log
from .llm import LLM
from .notion import Notion
from . import style
from . import notion as N

EMPTY = {"interests": [], "threads": [], "preferences": [], "notes": "",
         "recent_headlines": [], "feedback_seen": [], "pushed": {}}

MEMORY_SYSTEM = """你负责维护一位科研人员的“动态兴趣记忆”。输入包括：长期研究画像（用户亲手写的，稳定）、旧记忆、以及今天的新行为信号。
请输出更新后的记忆 JSON：
{
  "interests": [{"topic": "具体到方法/问题层面的兴趣点", "weight": 1-5, "trend": "up|steady|down",
                 "evidence": "最近的依据（≤40字）", "last_seen": "YYYY-MM-DD"}],
  "threads": [{"name": "值得持续跟进的线索（如某个方法路线、某个团队的系列工作、某个争论）",
               "summary": "目前进展（≤80字）", "last_seen": "YYYY-MM-DD"}],
  "preferences": ["阅读/内容偏好，例如：偏好有开源代码与扎实实验的工作；常收藏 AI 工作流技巧"],
  "notes": "一句话描述用户近期关注重心的变化"
}
规则：
1. 用户主动添加到收藏的内容最能反映真实兴趣，权重最高；其次是在推送里勾选“想深读”；仅被推送但没有被勾选的内容不应提高兴趣权重。
2. 兴趣点要具体（“RLVR 中的 reward hacking”优于“强化学习”），与长期画像重复的大类不必再写。
3. 超过 14 天没有新信号的兴趣，trend 设为 down 并降低 weight；weight 降到 0 就删除。线索超过 21 天没有进展就删除。
4. 不要捏造信号中不存在的事实。interests ≤ 15 条，threads ≤ 8 条，preferences ≤ 6 条。"""


def load(notion: Notion | None, page_id: str | None) -> dict:
    if not (notion and page_id):
        return dict(EMPTY)
    try:
        for b in notion.children(page_id):
            if b["type"] == "toggle":
                for c in notion.children(b["id"]):
                    if c["type"] == "code":
                        raw = "".join(t.get("plain_text", "") for t in c["code"]["rich_text"])
                        return {**EMPTY, **json.loads(raw)}
    except Exception as e:  # noqa: BLE001
        log.warning("memory load failed (starting fresh): %s", e)
    return dict(EMPTY)


def as_prompt(mem: dict, today: date | None = None) -> str:
    if not (mem.get("interests") or mem.get("threads")):
        return ""
    lines = ["# 动态记忆（系统根据用户近期行为自动学习，供参考）"]
    if mem.get("notes"):
        lines.append(f"近期重心：{mem['notes']}")
    for x in sorted(mem.get("interests", []), key=lambda x: -x.get("weight", 0)):
        lines.append(f"- 兴趣：{x.get('topic')}（权重 {x.get('weight')}，{x.get('trend')}）— {x.get('evidence', '')}")
    for t in mem.get("threads", []):
        lines.append(f"- 跟进线索：{t.get('name')} — {t.get('summary', '')}（{t.get('last_seen', '')}）")
    for p in mem.get("preferences", []):
        lines.append(f"- 偏好：{p}")
    past = [h for h in mem.get("recent_headlines", []) if not (today and h.startswith(today.isoformat()))]
    if past:   # a same-day rebuild must not treat today's own earlier headline as "yesterday"
        lines.append("最近几天的头条（避免重复，必要时承接）：")
        lines += [f"- {h}" for h in past[-5:]]
    return "\n".join(lines)


def drop_pushed(items: list[Item], mem: dict, today: date, days: int) -> tuple[list[Item], int]:
    """Remove items already pushed on an earlier day within the last `days` days.
    Runs before ranking, so freed slots go to the next-best new candidates."""
    cutoff, now = (today - timedelta(days=days)).isoformat(), today.isoformat()
    seen = {k for k, d in mem.get("pushed", {}).items() if cutoff <= d < now}
    kept = [it for it in items if it.key not in seen]
    return kept, len(items) - len(kept)


def mark_pushed(mem: dict, items: list[Item], today: date, days: int) -> None:
    cutoff = (today - timedelta(days=days)).isoformat()
    pushed = {k: d for k, d in mem.get("pushed", {}).items() if d >= cutoff}
    for it in items:
        pushed.setdefault(it.key, today.isoformat())
    mem["pushed"] = pushed


def collect_feedback(notion: Notion | None, parent: str, today: date, mem: dict, days: int = 3) -> list[str]:
    """Items the user ticked (☑) in the last few daily pages and that we haven't learnt from yet."""
    if not (notion and parent):
        return []
    seen = set(mem.get("feedback_seen", []))
    found: list[str] = []
    for k in range(1, days + 1):
        try:
            day_id = notion.find_child_page(parent, (today - timedelta(days=k)).isoformat())
            if not day_id:
                continue
            top = notion.children(day_id)
            blocks = [b for b in top if b["type"] == "to_do"]          # instant items live on the page itself
            for sub in top:
                if sub["type"] == "child_page":
                    blocks += notion.children(sub["id"])
            for b in blocks:
                if b["type"] == "to_do" and b["to_do"].get("checked"):
                    rt = b["to_do"]["rich_text"]
                    text = "".join(t.get("plain_text", "") for t in rt)
                    url = next((t["href"] for t in rt if t.get("href")), text)
                    if url not in seen:
                        seen.add(url)
                        found.append(text.strip())
                        mem.setdefault("feedback_seen", []).append(url)
        except Exception as e:  # noqa: BLE001
            log.warning("feedback scan failed for day -%d: %s", k, e)
    mem["feedback_seen"] = mem.get("feedback_seen", [])[-300:]
    log.info("feedback: %d newly ticked items", len(found))
    return found


def update(llm: LLM, profile: str, mem: dict, today: date, inbox: list[Item],
           ticked: list[str], digest: dict) -> dict:
    signals = [f"今天日期：{today.isoformat()}"]
    if inbox:
        signals.append("## 用户主动收藏的内容（最强信号）")
        from .classify import label
        signals += [f"- [{label(it)}] {it.title}" + (f"（用户备注：{it.note}）" if it.note else "")
                    + (f"\n  摘要：{it.text}" if it.extra.get("instant") and it.text else "") for it in inbox]
    if ticked:
        signals.append("## 用户在前几天的推送中勾选了“想深读”（强信号，弱于主动收藏）")
        signals += [f"- {t}" for t in ticked]
    signals.append("## 今天推送的主题（弱信号，仅用于更新线索进展）")
    signals += [f"- {th.get('title')}：{th.get('body', '')[:160]}" for th in digest.get("themes", [])]
    old = {k: mem.get(k) for k in ("interests", "threads", "preferences", "notes")}
    user = (f"# 长期研究画像\n{profile}\n\n# 旧记忆\n{json.dumps(old, ensure_ascii=False)}\n\n# 新信号\n"
            + "\n".join(signals))
    try:
        from .style import sanitize_obj
        new = sanitize_obj(llm.json(MEMORY_SYSTEM + "\n\n" + style.rules(), user, temperature=0.2, max_tokens=16000))
    except Exception as e:  # noqa: BLE001
        log.warning("memory update failed, keeping old memory: %s", e)
        new = old
    merged = {**mem, **{k: new.get(k, mem.get(k)) for k in ("interests", "threads", "preferences", "notes")}}
    if digest.get("headline"):
        headline = N._CITE.sub("", digest["headline"]).strip()
        past = [h for h in mem.get("recent_headlines", []) if not h.startswith(today.isoformat())]
        merged["recent_headlines"] = (past + [f"{today.isoformat()}：{headline}"])[-7:]
    return merged


_TREND = {"up": "📈", "steady": "➖", "down": "📉"}


def blocks(mem: dict, today: date) -> list[dict]:
    out = [N.callout(N.rich(f"本页由 PIS 根据你的收藏、勾选与每日推送自动维护（更新于 {today.isoformat()}）。"
                            "想调整长期方向请编辑“研究画像”页；想纠正这里的判断，直接在每日页面勾选/在 Inbox 写备注即可。"),
                     "🧠", "purple_background")]
    if mem.get("notes"):
        out.append(N.quote(N.rich(mem["notes"], italic=True)))
    if mem.get("interests"):
        out.append(N.heading("近期兴趣", 2))
        rows = [[N.rich(x.get("topic", ""), bold=True), N.rich("●" * int(x.get("weight", 1))),
                 N.rich(_TREND.get(x.get("trend"), "")), N.rich(x.get("evidence", ""), color="gray"),
                 N.rich(x.get("last_seen", ""))]
                for x in sorted(mem["interests"], key=lambda x: -x.get("weight", 0))]
        out.append(N.table(["兴趣点", "权重", "趋势", "依据", "最近"], rows))
    if mem.get("threads"):
        out.append(N.heading("持续跟进的线索", 2))
        out += [N.bullet(N.rich(t.get("name", ""), bold=True) + N.rich(f" — {t.get('summary', '')}（{t.get('last_seen', '')}）"))
                for t in mem["threads"]]
    if mem.get("preferences"):
        out.append(N.heading("阅读偏好", 2))
        out += [N.bullet(N.rich(p)) for p in mem["preferences"]]
    raw = json.dumps(mem, ensure_ascii=False, indent=1)
    out.append(N.divider())
    out.append(N.toggle(N.rich("⚙️ 机器可读数据（请勿手动修改）", color="gray"), [N.code(raw, "json")]))
    return out
