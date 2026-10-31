"""Deep dives stored in the「知识库」database.

Papers get the full-text, 12-question critical analysis; other saved items (open-source repos, AI tips,
research methods, news/opinion) get a template that fits what they are.

Each deep dive becomes a row (page) of the library database, so analyses accumulate, are searchable,
and are never generated twice for the same paper. The daily page links to them under each theme.
"""
from __future__ import annotations

import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from bs4 import BeautifulSoup

from .common import Item, http_get, log
from .llm import LLM
from .notion import Notion
from . import notion as N

ARXIV_ID = re.compile(r"(?:arxiv\.org/(?:abs|pdf|html)/|arXiv[:：\s]\s*)(\d{4}\.\d{4,5})", re.I)

PAPER_SYSTEM = """你是一位顶尖的机器学习研究者，正在为一位同行写一篇论文的深度解读与批判性分析。读者的研究背景附在后面，可以在合适的地方（尤其是第 10、12 问）结合，但不要硬套。

请严格按下面 12 个二级标题组织全文（标题原样使用），用 Markdown 输出：

## 1. 研究问题与价值
论文提出并解决的研究问题是什么（调研和补充背景）？为什么这个问题是重要的？解决这个问题能带来哪些价值？

## 2. 前人工作与不足
这个问题之前被解决了吗？之前的研究为什么存在不足？

## 3. 重建作者的思考路径
【重要】在正式讲方法之前，先重建作者可能的思考路径。不要使用论文自己的贡献作为前提，只使用之前已有的背景、失败模式、经验观察和相关工作。思考和模拟作者本人的思路和受到的 inspiration 以及 intuition，引导读者理解为什么作者可以基于已有知识想到这篇论文的 idea。

## 4. 核心 Intuition
这篇论文提出方法的 Intuition 是什么？易懂、清晰、concise 地讲出核心 idea 的本质。

## 5. 方法详解：一个完整例子
具体方法是什么？结合一个真实的例子讲解：输入、处理、输出完整的 pipeline。

## 6. 数学推导与理论背景
核心数学推导过程是什么（让数学基础薄弱的读者从理论视角理解方法）？如果有，补充理论背景，讲清理论基础和 intuition，公式逐个解释符号含义；如果论文没有实质数学内容，说明并跳过。

## 7. 实验设计：问题 → 实验 → 答案
论文如何设计实验来验证方法和 claim？每条按「提出了什么问题 → 设计了什么实验验证 → 答案是什么」的格式写成一个列表项。不需要很多数据细节，只要核心思路。

## 8. Take-aways
总结这篇论文的 take-aways。

## 9. 最脆弱的假设
【重要】这篇论文最脆弱的假设是什么？

## 10. 一周最小复现实验
如果读者有 1 周时间，能做一个什么最小复现实验来验证它的哪一点？给出模型/数据规模、关键步骤和判定标准。

## 11. 如果我反对它：反例设计
【重要】如果反对它，会怎么设计反例？

## 12. Follow-up Idea
基于你的知识和分析，提出一个 follow-up idea：要 novel，不是增量研究，从方法缺陷（Limitation）和真实需求出发，说清动机、核心做法和如何验证。
"""

STYLE = """## 写作要求
- 风格参考 Andrej Karpathy 和 Kaiming He，要有真人的语感。
- 使用详细的、准确的 claim，每句话都要有信息量，避免大空话和泛泛而谈。
- 使用流畅的文本，避免滥用破折号、引号，保持输出内容清洁流畅、易读性高。
- 使用真人逻辑，避免使用「不是……而是……」这种 AI 的低信息量结构。

## 格式要求
- 数学公式用 LaTeX：行内用 $...$，独立公式单独成行用 $$...$$。
- 可以用 **粗体** 标出关键概念，可以用列表；不要用表格，不要用 HTML。
- 直接从「## 1.」开始输出，不要写前言或结语。
- 原文中没有的数字和结论不要编造；如果只拿到了摘要或二手文章，在相关处如实说明哪些是推断。"""

DEEP_SYSTEM = PAPER_SYSTEM + "\n" + STYLE

_READER = "读者是一位 AI 研究者，研究背景附在后面。请为这位读者写一份解析，"

KIND_SYSTEMS = {
    "repo": _READER + """对象是一个开源项目/工具。请严格按下面的二级标题组织（标题原样使用）：

## 1. 它解决什么问题
具体痛点是什么，谁需要它，现有替代方案哪里不够用。
## 2. 核心思路与架构
关键设计是什么，主要模块怎样协作；如果背后有论文或特定算法，讲清原理。
## 3. 上手：最小可运行示例
安装方式和一个最小使用示例（用代码块），走一遍从输入到输出。只依据 README 和文章，没把握的命令要标注。
## 4. 与同类工具对比
和读者可能已经在用的方案比，优势和代价分别是什么。
## 5. 用在你的研究里
结合读者背景给出 1 到 3 个具体用法。
## 6. 局限与风险
成熟度、维护活跃度、license、依赖和常见坑。
## 7. 值不值得现在投入时间
给出明确建议（立即试用 / 收藏观望 / 不推荐）和理由。
""",
    "tip": _READER + """对象是一条 AI 使用技巧或工作流经验。请严格按下面的二级标题组织（标题原样使用）：

## 1. 技巧是什么
先用一句话说清，再展开。
## 2. 为什么有效
背后的机制（模型行为、上下文利用、工具链原理等）以及它成立的边界。
## 3. 照做：可复制的步骤
具体步骤，以及可以直接复制的 prompt、配置或命令（用代码块）。
## 4. 用到你的科研工作流
结合读者的研究，给出读论文、写代码、跑实验或写作中的具体场景，并给出改写后的示例。
## 5. 什么时候不要用
失效场景和风险（幻觉、隐私、成本、可复现性）。
## 6. 一句话 checklist
""",
    "method": _READER + """对象是一种科研方法论或研究习惯。请严格按下面的二级标题组织（标题原样使用）：

## 1. 核心主张
## 2. 背后的逻辑与证据
作者凭什么这样说，证据强度如何，有没有更强的反例。
## 3. 具体怎么做
可执行的步骤、频率和工具。
## 4. 一周试行方案
结合读者当前的研究主线，设计一个一周内就能试的版本，以及怎么判断它有没有用。
## 5. 局限与反面观点
## 6. 一句话带走
""",
    "news": _READER + """对象是一条行业资讯、访谈或观点文章。请严格按下面的二级标题组织（标题原样使用）：

## 1. 发生了什么
核心事实，明确区分事实和观点。
## 2. 背景与来龙去脉
## 3. 影响判断
对领域以及对读者研究方向分别意味着什么。
## 4. 可信度评估
信息来源是否一手，哪些说法可能夸大或缺乏证据。
## 5. 值得跟进的信号
接下来应该关注什么，出现什么迹象说明判断对或错。
""",
    "other": _READER + """请严格按下面的二级标题组织（标题原样使用）：

## 1. 核心内容
## 2. 为什么值得收藏
## 3. 对你有什么用
结合读者背景给出具体用法。
## 4. 需要注意什么
""",
}


def system_for(kind: str) -> str:
    if kind == "paper":
        return DEEP_SYSTEM
    return KIND_SYSTEMS.get(kind, KIND_SYSTEMS["other"]) + "\n" + STYLE.replace("「## 1.」", "第一个二级标题")


def find_arxiv_id(*texts: str) -> str | None:
    for t in texts:
        m = ARXIV_ID.search(t or "")
        if m:
            return m.group(1)
    return None


def _meta(aid: str) -> dict:
    """Title / authors / abstract from the arXiv abstract page (citation meta tags)."""
    try:
        r = http_get(f"https://arxiv.org/abs/{aid}", timeout=30, retries=2)
        if r.status_code != 200:
            return {}
        soup = BeautifulSoup(r.text, "html.parser")
        get = lambda n: [m.get("content", "") for m in soup.find_all("meta", attrs={"name": n})]  # noqa: E731
        return {"title": (get("citation_title") or [""])[0],
                "authors": ", ".join(a.split(", ")[-1] + " " + a.split(", ")[0] if ", " in a else a
                                     for a in get("citation_author")[:8]),
                "abstract": (get("citation_abstract") or [""])[0]}
    except Exception as e:  # noqa: BLE001
        log.warning("arXiv meta %s failed: %s", aid, e)
        return {}


def html_fulltext(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for m in soup.find_all("math"):                       # keep formulas as LaTeX
        alt = m.get("alttext", "")
        m.replace_with(f" ${alt}$ " if alt else " ")
    for t in soup.select("section.ltx_bibliography, .ltx_page_footer, nav, header, footer, script, style"):
        t.decompose()
    doc = soup.find("article") or soup.find(class_="ltx_document") or soup.body
    if not doc:
        return ""
    parts = []
    for el in doc.find_all(["h1", "h2", "h3", "h4", "p", "figcaption", "li"]):
        txt = re_space(el.get_text(" ", strip=True))
        if not txt:
            continue
        parts.append(("\n## " + txt) if el.name in ("h1", "h2", "h3", "h4") else txt)
    return "\n".join(parts)


def re_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def fulltext(aid: str, limit: int) -> tuple[str, str]:
    try:
        r = http_get(f"https://arxiv.org/html/{aid}", timeout=60, retries=2)
        if r.status_code == 200 and "ltx_" in r.text:
            txt = html_fulltext(r.text)
            if len(txt) > 3000:
                return txt[:limit], "arXiv HTML 全文"
    except Exception as e:  # noqa: BLE001
        log.warning("arXiv HTML %s failed: %s", aid, e)
    try:
        from pypdf import PdfReader
        r = http_get(f"https://arxiv.org/pdf/{aid}", timeout=90, retries=2)
        if r.status_code == 200:
            reader = PdfReader(io.BytesIO(r.content))
            txt = "\n".join((p.extract_text() or "") for p in reader.pages)
            if len(txt) > 3000:
                return txt[:limit], "arXiv PDF 全文"
    except Exception as e:  # noqa: BLE001
        log.warning("arXiv PDF %s failed: %s", aid, e)
    return "", ""


def github_context(slug: str, limit: int = 30000) -> str:
    """Repo metadata + README via the GitHub REST API (uses GITHUB_TOKEN in Actions for rate limits)."""
    import os
    h = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    out = []
    try:
        r = http_get(f"https://api.github.com/repos/{slug}", timeout=30, retries=2, headers=h)
        if r.status_code == 200:
            m = r.json()
            out.append(f"仓库：{m.get('html_url')}\n简介：{m.get('description')}\nStars：{m.get('stargazers_count')}"
                       f"  Forks：{m.get('forks_count')}  主要语言：{m.get('language')}"
                       f"  License：{(m.get('license') or {}).get('spdx_id')}  最近推送：{m.get('pushed_at')}")
        r = http_get(f"https://api.github.com/repos/{slug}/readme", timeout=30, retries=2,
                     headers={**h, "Accept": "application/vnd.github.raw"})
        if r.status_code == 200:
            out.append("README：\n" + r.text[:limit])
    except Exception as e:  # noqa: BLE001
        log.warning("GitHub %s failed: %s", slug, e)
    return "\n\n".join(out)


def pick(numbered: list[tuple[int, Item]], cfg: dict) -> list[tuple[int, Item]]:
    """Inbox items first (your explicit interest), then the highest-scoring papers."""
    inbox, papers = [], []
    for n, it in numbered:
        if it.source == "inbox" and cfg.get("include_inbox", True):
            kind = it.extra.setdefault("kind", "other")
            if kind == "paper" and not it.extra.get("arxiv_id"):
                aid = find_arxiv_id(it.url, it.text)
                if aid:
                    it.extra["arxiv_id"] = aid
            if ((kind == "paper" and it.extra.get("arxiv_id")) or (kind == "repo" and it.extra.get("github"))
                    or len(it.text) >= cfg.get("min_article_chars", 400)):   # short repo posts: README carries it
                inbox.append((n, it))
        elif it.source in ("arxiv", "hf") and it.score >= cfg.get("min_score", 8) and it.extra.get("arxiv_id"):
            it.extra["kind"] = "paper"
            papers.append((n, it))
    papers.sort(key=lambda x: -x[1].score)
    return (inbox + papers)[: cfg.get("max_items", 6)]


def _existing(notion: Notion, lib: str, url: str) -> str | None:
    try:
        rows = notion.query_db(lib, {"property": "URL", "url": {"equals": url}})
        return rows[0]["id"] if rows else None
    except Exception as e:  # noqa: BLE001
        log.warning("library lookup failed: %s", e)
        return None


def _header(it: Item, title: str, authors: str, aid: str | None, basis: str, emoji: str = "📄") -> list[dict]:
    links = []
    if it.extra.get("github"):
        links += N.rich("GitHub", link=f"https://github.com/{it.extra['github']}") + N.rich(" · ")
    if aid:
        links += N.rich("arXiv", link=f"https://arxiv.org/abs/{aid}") + N.rich(" · ") + \
                 N.rich("PDF", link=f"https://arxiv.org/pdf/{aid}") + N.rich(" · ") + \
                 N.rich("HF 讨论", link=f"https://huggingface.co/papers/{aid}")
    if it.source == "inbox":
        links += (N.rich(" · ") if links else []) + N.rich("原文章", link=it.url)
    c = N.callout(N.rich(title, bold=True), emoji, "gray_background")
    kids = []
    if authors:
        kids.append(N.paragraph(N.rich(authors, color="gray")))
    if links:
        kids.append(N.paragraph(links))
    kids.append(N.paragraph(N.rich(f"解读依据：{basis}", color="gray", italic=True)))
    if it.note:
        kids.append(N.paragraph(N.rich("我的备注：" + it.note, color="brown")))
    c["callout"]["children"] = kids
    return [c, N.toc()]


def analyse(llm: LLM, notion: Notion, lib: str, profile: str, n: int, it: Item, today: date,
            cfg: dict) -> tuple[int, str] | None:
    from .classify import KINDS
    kind = it.extra.get("kind", "paper")
    kind_label, emoji = KINDS.get(kind, KINDS["other"])
    aid = it.extra.get("arxiv_id") if kind == "paper" else None
    gh = it.extra.get("github") if kind == "repo" else None
    url = f"https://arxiv.org/abs/{aid}" if aid else (f"https://github.com/{gh}" if gh else it.url)
    found = _existing(notion, lib, url)
    if found:
        log.info("deep dive [%d] already in library", n)
        return n, found

    note = f"读者收藏时的备注：{it.note}\n" if it.note else ""
    if kind == "paper":
        meta = _meta(aid) if aid else {}
        title = meta.get("title") or it.title
        authors = meta.get("authors") or it.authors
        abstract = meta.get("abstract") or (it.text if it.source != "inbox" else "")
        body, basis = fulltext(aid, cfg.get("max_chars", 150000)) if aid else ("", "")
        if not body:
            if it.source == "inbox" and it.text:
                body, basis = it.text, "公众号/网页文章（二手解读，非论文原文）"
            else:
                body, basis = abstract, "仅摘要（未能获取全文，深度有限）"
        user = (f"# 读者研究背景\n{profile[:3000]}\n\n# 论文\n标题：{title}\n作者：{authors}\n"
                f"摘要：{abstract}\n{note}\n# 正文（{basis}）\n{body}")
    else:
        title, authors = it.title, it.authors
        body, basis = it.text, f"收藏的文章（{kind_label}）"
        if gh:
            repo = github_context(gh)
            if repo:
                body, basis = f"{repo}\n\n# 介绍文章\n{it.text}", "GitHub README + 介绍文章"
        user = (f"# 读者研究背景\n{profile[:3000]}\n\n# 收藏内容（类型：{kind_label}）\n标题：{title}\n"
                f"{note}\n# 正文（{basis}）\n{body[:cfg.get('max_chars', 150000)]}")
    try:
        md = llm.text(system_for(kind), user, temperature=0.5, max_tokens=cfg.get("max_tokens", 32768))
    except Exception as e:  # noqa: BLE001
        log.error("deep dive [%d] %s failed: %s", n, title[:60], e)
        return None

    props = {
        "Name": {"title": [{"text": {"content": title[:200]}}]},
        "URL": {"url": url},
        "日期": {"date": {"start": today.isoformat()}},
        "来源": {"select": {"name": (it.origin or "未知").split(" · ")[0].replace(",", " ")[:90]}},
        "类型": {"select": {"name": kind_label}},
    }
    if it.score and it.source != "inbox":
        props["相关度"] = {"number": it.score}
    blocks = _header(it, title, authors, aid, basis, emoji) + N.md_to_blocks(md)
    try:
        pid = notion.create_db_page(lib, props, blocks, emoji=emoji)
    except Exception as e:  # noqa: BLE001
        log.error("writing deep dive [%d] failed: %s", n, e)
        return None
    log.info("deep dive [%d] %s -> %s (%s)", n, title[:60], pid, basis)
    return n, pid


def run(llm: LLM, notion: Notion, lib: str, profile: str, numbered: list[tuple[int, Item]],
        today: date, cfg: dict) -> dict[int, str]:
    targets = pick(numbered, cfg)
    if not targets:
        return {}
    log.info("deep dives: %d targets", len(targets))
    with ThreadPoolExecutor(max_workers=cfg.get("workers", 3)) as ex:
        res = ex.map(lambda t: analyse(llm, notion, lib, profile, t[0], t[1], today, cfg), targets)
        return dict(r for r in res if r)
