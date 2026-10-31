"""Classify hand-saved links: not everything you save is a paper."""
from __future__ import annotations

from .common import Item, log
from .llm import LLM

KINDS = {
    "paper": ("论文", "🔬"),
    "repo": ("开源项目", "🧰"),
    "tip": ("AI 技巧", "💡"),
    "method": ("科研方法", "🧭"),
    "news": ("资讯观点", "📰"),
    "other": ("其他", "📎"),
}

CLASSIFY_SYSTEM = """判断用户收藏的每篇文章属于哪一类，依据文章的主体内容，而不是顺带提到的东西：
- paper：主体是介绍/解读某一篇（或少数几篇）具体的研究工作或论文
- repo：主体是介绍某个开源仓库、工具、框架、模型权重的功能与用法
- tip：AI 工具或大模型的使用技巧、prompt、工作流、配置经验
- method：科研方法论与习惯，如选题、读论文、写作、实验管理、时间管理
- news：行业动态、产品发布、访谈、观点评论、综述性趋势分析
- other：以上都不是
只输出 JSON：{"items": [{"id": <int>, "kind": "paper|repo|tip|method|news|other", "why": "≤20字"}]}"""


def label(it: Item) -> str:
    return KINDS.get(it.extra.get("kind", "other"), KINDS["other"])[0]


def _heuristic(it: Item) -> str:
    if it.extra.get("github") and not it.extra.get("arxiv_id"):
        return "repo"
    if it.extra.get("arxiv_id"):
        return "paper"
    return "other"


def classify(llm: LLM, items: list[Item]) -> None:
    """Sets it.extra['kind'] and makes the kind visible in it.origin (e.g. '微信公众号 · AI 技巧')."""
    if not items:
        return
    lines = []
    for i, it in enumerate(items):
        hints = []
        if it.extra.get("arxiv_id"):
            hints.append(f"含 arXiv 链接 {it.extra['arxiv_id']}")
        if it.extra.get("github"):
            hints.append(f"含 GitHub 链接 {it.extra['github']}")
        lines.append(f"[{i}] {it.title}\n" + (f"用户备注：{it.note}\n" if it.note else "") +
                     (f"线索：{'；'.join(hints)}\n" if hints else "") + f"正文开头：{it.text[:900]}")
    result: dict[int, str] = {}
    try:
        d = llm.json(CLASSIFY_SYSTEM, "\n\n".join(lines), temperature=0.0, max_tokens=1500)
        for x in d.get("items", []):
            if x.get("kind") in KINDS:
                result[int(x["id"])] = x["kind"]
    except Exception as e:  # noqa: BLE001
        log.warning("classification failed, using heuristics: %s", e)
    for i, it in enumerate(items):
        it.extra["kind"] = result.get(i) or _heuristic(it)
        it.origin = f"{it.origin} · {label(it)}"
    log.info("inbox kinds: %s", [it.extra["kind"] for it in items])
