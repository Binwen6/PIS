"""Offline end-to-end test: fake HTTP sources, fake DeepSeek, fake Notion."""
import json
import re
from datetime import date
import sys
import types
from email.utils import format_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pis import common, main as M, notion as N  # noqa: E402
from pis.sources import arxiv  # noqa: E402

ARXIV_RSS = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>cs.CL updates</title>
<item><title>GRPO Scaling for Agentic Reasoning</title><link>https://arxiv.org/abs/2610.00001</link>
<description>arXiv:2610.00001v1 Announce Type: new
Abstract: We study reinforcement learning with verifiable rewards for LLM agents.</description>
<category>cs.CL</category><arxiv:announce_type>new</arxiv:announce_type><dc:creator>Alice, Bob, Carol, Dan</dc:creator></item>
<item><title>Better Segmentation of Cats</title><link>https://arxiv.org/abs/2610.00002</link>
<description>arXiv:2610.00002v1 Announce Type: cross
Abstract: A small improvement on cat segmentation.</description>
<category>cs.CV</category><arxiv:announce_type>cross</arxiv:announce_type><dc:creator>Eve</dc:creator></item>
<item><title>Old paper revised</title><link>https://arxiv.org/abs/2401.99999</link>
<description>arXiv:2401.99999v3 Announce Type: replace
Abstract: revision.</description>
<arxiv:announce_type>replace</arxiv:announce_type></item>
</channel></rss>"""

HF = [{"paper": {"id": "2610.00001", "title": "GRPO Scaling for Agentic Reasoning", "summary": "...", "upvotes": 88,
                 "authors": [{"name": "Alice"}]}},
      {"paper": {"id": "2610.00003", "title": "Trending Test-Time Scaling", "summary": "TTS for reasoning.",
                 "upvotes": 40, "authors": []}}]


def blog_rss():
    now = format_datetime(common.utcnow())
    return f"""<?xml version="1.0"?><rss version="2.0"><channel><title>Blog</title>
<item><title>New reasoning model released</title><link>https://example.com/post</link>
<pubDate>{now}</pubDate><description>&lt;p&gt;We release a reasoning model.&lt;/p&gt;</description></item>
<item><title>Ancient post</title><link>https://example.com/old</link>
<pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate><description>old</description></item>
</channel></rss>""".encode()


WECHAT_HTML = """<html><head><meta property="og:title" content="og"></head><body>
<h1 id="activity-name">公众号：Agent 评测新基准</h1><div id="js_content"><p>本文介绍了一个新的 Agent 评测基准，""" + "内容" * 50 + """</p><a href="https://arxiv.org/abs/2610.55555">论文</a></div></body></html>"""


class Resp:
    def __init__(self, content=b"", status=200, js=None, text=None):
        self.content, self.status_code, self._js = content, status, js
        self.text = text if text is not None else content.decode("utf-8", "ignore")
        self.encoding, self.apparent_encoding, self.headers = "utf-8", "utf-8", {}

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


REPO_HTML = """<html><body><h1 id="activity-name">一个让 agent 共享 KV cache 的开源库</h1><div id="js_content"><p>""" + \
    "安装后即可使用。" * 40 + """<a href="https://github.com/foo/bar">repo</a> 参见 github.com/foo/bar 与 github.com/features/x</p></div></body></html>"""


def fake_get(url, **kw):
    if "api.github.com/repos/foo/bar/readme" in url:
        return Resp(text="# bar\npip install bar")
    if "api.github.com/repos/foo/bar" in url:
        return Resp(js={"html_url": "https://github.com/foo/bar", "description": "KV sharing", "stargazers_count": 42,
                        "forks_count": 1, "language": "Python", "license": {"spdx_id": "MIT"}, "pushed_at": "2026-10-30"})
    if "mp.weixin.qq.com/s/repo" in url:
        return Resp(text=REPO_HTML)
    if "rss.arxiv.org" in url:
        return Resp(ARXIV_RSS)
    if "daily_papers" in url:
        return Resp(js=HF if url.endswith("10-31") else [])
    if "mp.weixin.qq.com" in url:
        return Resp(text=WECHAT_HTML)
    if "arxiv.org/abs/" in url:
        return Resp(text='<meta name="citation_title" content="Latent Agents"><meta name="citation_author" content="Doe, Jane">'
                         '<meta name="citation_abstract" content="We let agents read each other\'s hidden states.">')
    if "arxiv.org/html/" in url:
        return Resp(text='<article class="ltx_document"><h2>Method</h2><p>We align ' + "x " * 2000 +
                         '<math alttext="z_a = R z_b"></math></p><section class="ltx_bibliography"><p>REFS</p></section></article>')
    if "fail" in url:
        return Resp(status=404)
    return Resp(blog_rss())


class FakeLLM:
    def __init__(self, *a, **k):
        self.model, self.usage = "fake", {"prompt_tokens": 1, "completion_tokens": 1}

    def text(self, system, user, **kw):
        if "开源项目" in system:                                              # repo template, not the paper one
            assert "## 3. 上手：最小可运行示例" in system and "12. Follow-up" not in system
            assert "Stars：42" in user and "pip install bar" in user          # GitHub metadata + README fed in
            return "## 1. 它解决什么问题\n共享 KV cache。\n```bash\npip install bar\n```\n" + "说明" * 100
        assert "深度解读" in system and "## 12. Follow-up Idea" in system
        assert "AGENTS 测试规则" in system
        assert "$z_a = R z_b$" in user and "REFS" not in user          # LaTeX kept, bibliography dropped
        self.deep_calls = getattr(self, "deep_calls", 0) + 1
        return "## 1. 研究问题与价值\n读取搭档的 $h_t$ 隐状态。\n$$\n\\min_R \\|A-RB\\|\n$$\n- 要点\n" + "正文" * 100

    def json(self, system, user, **kw):
        if "刚收藏" in system:
            ids = [int(x) for x in re.findall(r"^\[(\d+)\]", user.split("# 新收藏")[-1], re.M)]
            return {"items": [{"id": i, "tldr": f"一句话{i}", "detail": f"细节{i}"} for i in ids]}
        if "判断用户收藏" in system:
            chunks = re.split(r"^\[(\d+)\] ", user, flags=re.M)[1:]
            return {"items": [{"id": int(i), "kind": "repo" if "GitHub" in c else "paper", "why": "x"}
                              for i, c in zip(chunks[::2], chunks[1::2])]}
        body = user.split("# 待评分条目")[-1].split("# 今日条目")[-1]
        ids = [int(x) for x in re.findall(r"^\[(\d+)\]", body, re.M)]
        if "评分" in system:
            assert "最近主动收藏" in user and "Agent 评测新基准" in user        # saves shape today's ranking
            return {"results": [{"id": i, "score": 2 if "Cats" in body.split(f"[{i}]")[1][:80] else 8,
                                 "why": "命中 RL 推理"} for i in ids]}
        if "动态兴趣记忆" in system:
            assert "Agent 评测新基准" in user and "Old ticked paper" in user     # inbox + ticked are fed in
            assert "[开源项目]" in user and "最强信号" in user
            assert "AGENTS 测试规则" in system
            return {"interests": [{"topic": "Agent 评测", "weight": 4, "trend": "up", "evidence": "收藏+勾选",
                                   "last_seen": "2026-10-31"}],
                    "threads": [{"name": "RLVR for agents", "summary": "GRPO 扩展到 agent", "last_seen": "2026-10-31"}],
                    "preferences": ["偏好有代码"], "notes": "从推理转向 agent 评测"}
        assert "动态记忆" in user and "RLVR for agents" in user                   # memory reaches the digest prompt
        assert "类型：开源项目" in user and "类型：论文" in user                  # saved items carry their kind
        assert "AGENTS 测试规则" in system
        assert "昨天头条" in user and "同日旧头条" not in user                     # same-day rebuild ignores own headline
        return {"headline": "RLVR 走向 Agent [1]", "takeaways": ["**GRPO** 用于 `Agent` [1]", "收藏 [4]"],
                "themes": [{"emoji": "🧠", "title": "推理", "body": "讨论 [1][4]，以及不存在的 [99]。",
                            "so_what": "可对比 [1]", "refs": [1, 2, 99], "key_ref": 1},
                           {"emoji": "🛠", "title": "工具", "body": "[3]", "refs": [3, 4], "key_ref": 1}],
                "threads": [{"name": "RLVR for agents", "update": "新进展 [1]"}],
                "items": [{"id": i, "tldr": f"要点{i}", "detail": "收藏总结" if i == ids[-1] else ""} for i in ids]}


def check_blocks(blocks, depth=0):
    """Notion API constraints: <=100 children/request, <=2 nesting levels, <=2000 chars & <=100 rich_text items."""
    assert depth <= 2, "nesting too deep"
    for b in blocks:
        data = b[b["type"]]
        rts = [data.get("rich_text", [])] + [c for r in data.get("cells", []) for c in [r]]
        for rt in rts:
            assert len(rt) <= 100 and all(len(t.get("text", {}).get("content", "")) <= 2000 for t in rt)
        kids = data.get("children", [])
        assert len(kids) <= 100
        if kids:
            check_blocks(kids, depth + 1)


MEM_JSON = json.dumps({"interests": [], "threads": [{"name": "RLVR for agents", "summary": "x", "last_seen": "2026-10-29"}],
                       "preferences": [], "notes": "", "recent_headlines": ["2026-10-30：昨天头条", "2026-10-31：同日旧头条"], "feedback_seen": []})


class FakeNotion:
    def __init__(self, *a, **k):
        self.pages, self.updated, self.replaced, self.db_pages = [], [], None, []

    def children_pis(self):
        return [{"id": "prof", "type": "child_page", "child_page": {"title": "研究画像"}},
                {"id": "mem", "type": "child_page", "child_page": {"title": "🧠 记忆"}},   # legacy title -> renamed
                {"id": "db", "type": "child_database", "child_database": {"title": "Inbox"}},
                {"id": "lib", "type": "child_database", "child_database": {"title": "论文库"}},   # legacy -> 知识库
                {"id": "agents", "type": "child_page", "child_page": {"title": "AGENTS.md"}}]

    def create_db_page(self, db, props, blocks, emoji=""):
        check_blocks(blocks)
        json.dumps(blocks)
        self.db_pages.append((db, props, blocks))
        return f"deep-{len(self.db_pages)}"

    def req(self, method, path, json=None):
        self.reqs = getattr(self, "reqs", []) + [(method, path, json)]
        assert method == "PATCH" and path in ("/pages/mem", "/databases/lib", "/databases/db"), path
        return {}

    def find_child_page(self, parent, title):
        return "day-1030" if (parent, title) == ("pis", "2026-10-30") else None

    def children(self, bid):
        if bid == "pis":
            return self.children_pis()
        if bid == "mem":
            return [{"id": "tg", "type": "toggle", "toggle": {}}]
        if bid == "tg":
            return [{"id": "c", "type": "code", "code": {"rich_text": [{"plain_text": MEM_JSON}]}}]
        if bid == "day-1030":
            return [{"id": "sub", "type": "child_page", "child_page": {"title": "论文精选（3）"}}]
        if bid == "sub":
            return [{"type": "to_do", "to_do": {"checked": True, "rich_text": [
                        {"plain_text": "[1] "}, {"plain_text": "Old ticked paper", "href": "https://arxiv.org/abs/2610.0"}]}},
                    {"type": "to_do", "to_do": {"checked": False, "rich_text": [{"plain_text": "Unticked"}]}}]
        return []

    def replace_content(self, pid, blocks):
        check_blocks(blocks)
        json.dumps(blocks)
        self.replaced = (pid, blocks)

    def page_text(self, pid):
        if pid == "agents":
            return "禁止使用双破折号的句式（AGENTS 测试规则）"
        return "## 核心兴趣\n- reinforcement learning, reasoning, agents"

    def create_page(self, parent, title, blocks, emoji="📰"):
        check_blocks(blocks)
        json.dumps(blocks)  # must be serialisable
        self.pages.append((parent, title, blocks))
        return f"page-{len(self.pages)}"

    def query_db(self, db, f=None, sorts=None):
        if db == "lib":
            return []
        return [{"id": "row1", "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "https://mp.weixin.qq.com/s/abc"}]},
            "URL": {"type": "url", "url": None},
            "Note": {"type": "rich_text", "rich_text": [{"plain_text": "想看评测设计"}]},
            "Processed": {"type": "checkbox", "checkbox": False}}},
                {"id": "row2", "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "https://mp.weixin.qq.com/s/repo"}]},
            "URL": {"type": "url", "url": None},
            "Note": {"type": "rich_text", "rich_text": []},
            "Processed": {"type": "checkbox", "checkbox": False}}}]

    def update_props(self, pid, props):
        self.updated.append((pid, props))


def test_arxiv_parse():
    items = arxiv.parse_feed(ARXIV_RSS)
    assert [i.extra["arxiv_id"] for i in items] == ["2610.00001", "2610.00002"]
    assert items[0].text.startswith("We study"), items[0].text
    assert items[0].authors.startswith("Alice")


def test_citations():
    rt = N.rich_with_citations("见 [1][2] 和 [3，4] 以及 [9]", {1: "u1", 2: "u2", 3: "u3", 4: "u4"})
    linked = [t["text"]["content"] for t in rt if t["text"].get("link")]
    assert linked == ["1", "2", "3", "4"]
    assert "".join(t["text"]["content"] for t in rt) == "见 [1][2] 和 [3,4] 以及 [9]"


def test_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setattr(common.requests, "get", fake_get)
    monkeypatch.setattr(M, "LLM", FakeLLM)
    fake = FakeNotion()
    monkeypatch.setattr(M, "Notion", lambda *a, **k: fake)
    for k, v in {"NOTION_TOKEN": "x", "NOTION_PIS_PAGE_ID": "pis",
                 "DEEPSEEK_API_KEY": "k"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(M, "ROOT", _root_copy(tmp_path))
    args = types.SimpleNamespace(dry_run=False, force=False, date="2026-10-31")
    assert M.run(args) == 0

    titles = [t for _, t, _ in fake.pages]
    assert titles == ["2026-10-31", "论文精选（2）", "动态与博客（1）", "我的收藏（2）"], titles
    main = fake.pages[0][2]
    types_ = [b["type"] for b in main]
    for t in ("callout", "table_of_contents", "heading_2", "quote", "bookmark", "toggle"):
        assert t in types_, (t, types_)
    assert main[types_.index("bookmark")]["bookmark"]["url"] == "https://huggingface.co/papers/2610.00001"
    mer = [b for b in main if b["type"] == "toggle"][0]["toggle"]["children"][0]["code"]
    assert mer["language"] == "mermaid" and "I99" not in mer["rich_text"][0]["text"]["content"]
    sub = fake.pages[1][2]
    assert sum(b["type"] == "to_do" for b in sub) == 2
    # memory page rewritten, ticked feedback remembered so it is not counted twice
    pid, mblocks = fake.replaced
    raw = [b for b in mblocks if b["type"] == "toggle"][0]["toggle"]["children"][0]["code"]["rich_text"]
    mem = json.loads("".join(t["text"]["content"] for t in raw))
    assert pid == "mem" and mem["interests"][0]["topic"] == "Agent 评测"
    assert mem["feedback_seen"] == ["https://arxiv.org/abs/2610.0"]
    assert mem["recent_headlines"] == ["2026-10-30：昨天头条", "2026-10-31：RLVR 走向 Agent"]
    assert mem["pushed"] == {"arxiv:2610.00001": "2026-10-31", "arxiv:2610.00003": "2026-10-31",
                             "https://example.com/post": "2026-10-31"}             # today's picks recorded
    paths = {(m, p) for m, p, _ in fake.reqs}
    assert ("PATCH", "/pages/mem") in paths and ("PATCH", "/databases/lib") in paths   # renames + 类型 column
    assert any(j.get("title", [{}])[0].get("text", {}).get("content") == "知识库" for _, p, j in fake.reqs if j and "title" in j)
    assert sum(b["type"] == "bookmark" for b in main) == 1    # same key item is not bookmarked twice
    # deep dives: inbox article links an arXiv paper -> analysed from full text; linked under its theme
    assert len(fake.db_pages) == 4                       # 2 saved items + two papers scored >= 8
    repo = next(p for p in fake.db_pages if p[1]["URL"]["url"] == "https://github.com/foo/bar")
    assert repo[1]["类型"]["select"]["name"] == "开源项目" and repo[1]["来源"]["select"]["name"] == "微信公众号"
    assert any(b["type"] == "code" for b in repo[2])
    i, (db, props, dblocks) = next((i, p) for i, p in enumerate(fake.db_pages)
                                  if p[1]["URL"]["url"] == "https://arxiv.org/abs/2610.55555")
    assert db == "lib" and props["类型"]["select"]["name"] == "论文"
    assert props["Name"]["title"][0]["text"]["content"] == "Latent Agents"
    assert any(b["type"] == "equation" for b in dblocks)
    assert any(t["type"] == "equation" for b in dblocks if b["type"] == "paragraph" for t in b["paragraph"]["rich_text"])
    links = [b["link_to_page"]["page_id"] for b in main if b["type"] == "link_to_page"]
    assert f"deep-{i + 1}" in links, links
    saved = fake.pages[3][2]
    assert any(k["type"] == "link_to_page" for b in saved if b["type"] == "to_do" for k in b["to_do"].get("children", []))
    heads = [b["heading_3"]["rich_text"][0]["text"]["content"] for b in saved if b["type"] == "heading_3"]
    assert heads == ["🔬 论文", "🧰 开源项目"], heads
    assert fake.updated and fake.updated[0][1]["Processed"]["checkbox"] is True
    assert "Agent 评测新基准" in fake.updated[0][1]["Name"]["title"][0]["text"]["content"]
    md = (M.ROOT / "out" / "2026-10-31.md").read_text()
    print(md)
    assert "[[1](https://arxiv.org/abs/2610.00001)]" in md


def _root_copy(tmp):
    import shutil
    src = Path(__file__).resolve().parent.parent
    shutil.copytree(src / "config", tmp / "config")
    return tmp


def test_bootstrap_creates_missing(tmp_path):
    from pis import bootstrap
    root = _root_copy(tmp_path)
    created = []

    class N0(FakeNotion):
        def children(self, bid):
            return []

        def create_page(self, parent, title, blocks, emoji=""):
            check_blocks(blocks)
            created.append(title)
            return "new-" + title

        def req(self, method, path, json=None):
            if method == "PATCH":                       # new Inbox columns
                assert path == "/databases/new-Inbox" and "已汇总" in json["properties"]
                return {}
            assert path == "/databases" and json["parent"]["page_id"] == "40ad4b61-755e-80b0-a159-f34c3f246739"
            created.append(json["title"][0]["text"]["content"])
            return {"id": "new-" + json["title"][0]["text"]["content"]}

    import yaml
    cfg = yaml.safe_load((root / "config" / "sources.yaml").read_text())
    ids = bootstrap.ensure(N0(), cfg, root)
    assert created == ["研究画像", "记忆", "Inbox", "知识库"] and ids["library"] == "new-知识库"


def test_model_fallback(monkeypatch):
    from pis import llm as L
    calls = []

    class R:
        def __init__(self, code, body):
            self.status_code, self._b, self.text = code, body, json.dumps(body)

        def json(self):
            return self._b

        def raise_for_status(self):
            pass

    def post(url, json=None, **kw):
        calls.append(json["model"])
        if json["model"] == "deepseek-flash":
            return R(400, {"error": {"message": "Model Not Exist"}})
        return R(200, {"choices": [{"message": {"content": '{"ok": 1}'}}], "usage": {}})

    monkeypatch.setattr(L.requests, "post", post)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    c = L.LLM("https://x", "deepseek-flash", api_key="k", fallbacks=["deepseek-chat"])
    assert c.json("s", "u") == {"ok": 1} and calls == ["deepseek-flash", "deepseek-chat"]


def test_github_annotations(capsys):
    import logging
    from pis.common import GitHubAnnotations
    h = GitHubAnnotations(logging.WARNING)
    h.setFormatter(logging.Formatter("%(message)s"))
    lg = logging.getLogger("t")
    lg.addHandler(h)
    try:
        raise ValueError("boom")
    except ValueError:
        lg.exception("run failed 100%")
    out = capsys.readouterr().out
    assert out.startswith("::error::run failed 100%25%0ATraceback") and "ValueError: boom" in out


def test_github_repo_detection():
    from pis.web import github_repo_in
    assert github_repo_in(REPO_HTML) == "foo/bar"
    assert github_repo_in("see github.com/features/copilot") == ""


def test_digest_degrades_gracefully():
    from pis.common import Item
    from pis.digest import make_digest
    calls = []

    class Flaky:
        def json(self, system, user, **kw):
            calls.append(len(user))
            raise RuntimeError("bad JSON; finish_reason=length")

    items = [(1, Item(source="inbox", title="t", url="u", text="x" * 3000))]
    d = make_digest(Flaky(), "ctx", items)
    assert len(calls) == 1 and calls[0] > 3000               # full text, no compaction
    assert d["headline"].startswith("今日摘要生成失败") and 1 in d["items_by_id"]


def test_backfill(monkeypatch, tmp_path):
    from pis import backfill as B, main as M2
    monkeypatch.setattr(common.requests, "get", fake_get)
    monkeypatch.setattr(B, "LLM", FakeLLM)
    fake = FakeNotion()
    appended = []
    fake.append = lambda pid, blocks: appended.append((pid, blocks))
    monkeypatch.setattr(B, "Notion", lambda *a, **k: fake)
    monkeypatch.setattr(B, "ROOT", _root_copy(tmp_path))
    monkeypatch.setattr(M2, "ROOT", B.ROOT)
    for k, v in {"NOTION_TOKEN": "x", "NOTION_PIS_PAGE_ID": "pis", "DEEPSEEK_API_KEY": "k"}.items():
        monkeypatch.setenv(k, v)
    code = B.run(["2610.39302", "https://mp.weixin.qq.com/s/repo"], date(2026, 10, 30))
    assert code == 0
    urls = [p[1]["URL"]["url"] for p in fake.db_pages]
    assert urls == ["https://arxiv.org/abs/2610.39302", "https://github.com/foo/bar"], urls
    assert fake.db_pages[0][1]["Name"]["title"][0]["text"]["content"] == "Latent Agents"   # title from arXiv meta
    pid, blocks = appended[0]
    assert pid == "day-1030" and blocks[0]["type"] == "heading_2"
    assert [b["link_to_page"]["page_id"] for b in blocks[1:]] == ["deep-1", "deep-2"]


def test_sanitize_style():
    from pis.style import sanitize
    s = sanitize("提速 2.6×，3×3 卷积，见「原文」，检索头 · 稀疏性，公式 $a \\times b \\cdot c$ 和 `x·y` 保留 ✓")
    assert s == "提速 2.6 倍，3x3 卷积，见“原文”，检索头、稀疏性，公式 $a \\times b \\cdot c$ 和 `x·y` 保留 ", s


class _IdLLM:
    def __init__(self, verdict=None):
        self.verdict = verdict

    def json(self, system, user, **kw):
        if "候选论文" in system:
            assert "Adaptive Video Tokens via Information" in user           # candidate abstracts are shown
            return self.verdict
        assert "英文原标题" in system
        return {"is_paper": True, "title": "InfoTok: Information-Theoretic Adaptive Video Tokenization",
                "method_name": "InfoTok", "authors": ["A. Smith"], "keywords": ["video tokenizer", "ELBO"],
                "venue": "ICLR 2026", "arxiv_id": ""}


ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/abs/2610.11111v1</id><title>Unrelated Paper About Cats</title><summary>cats</summary></entry>
  <entry><id>http://arxiv.org/abs/2610.77777v2</id><title>Adaptive Video Tokens via Information
    Theory</title><summary>We allocate tokens by ELBO.</summary></entry></feed>"""


import pis.resolve as _resolve_mod  # noqa: E402
_resolve_mod.S2_INTERVAL = 0


def test_s2_backs_off_on_429(monkeypatch):
    from pis import resolve
    calls = []

    def get(url, **kw):
        calls.append(url)
        return Resp(status=429) if len(calls) == 1 else Resp(js={"data": [{"title": "T", "externalIds": {"ArXiv": "2610.1"}}]})
    monkeypatch.setattr(common.requests, "get", get)
    monkeypatch.setattr(resolve.time, "sleep", lambda s: None)
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    assert resolve._s2("q")[0]["arxiv_id"] == "2610.1" and len(calls) == 2


def _get_no_s2(url, **kw):
    if "export.arxiv.org" in url:
        return Resp(ATOM)
    return Resp(js={"data": [], "notes": []})


def test_resolve_exact_title(monkeypatch):
    from pis import resolve
    from pis.common import Item
    atom = ATOM.replace(b"Adaptive Video Tokens via Information\n    Theory",
                        b"InfoTok: Information-Theoretic Adaptive Video Tokenization")
    monkeypatch.setattr(common.requests, "get", lambda url, **kw: Resp(atom) if "arxiv" in url else Resp(js={"data": []}))
    hit = resolve.find_paper(_IdLLM(), Item(source="inbox", title="香农", url="u", text="文章正文"))
    assert hit["arxiv_id"] == "2610.77777"


def test_resolve_verified_by_model(monkeypatch):
    """Guessed title differs from the real one: the model picks the right candidate from the abstracts."""
    from pis import resolve
    from pis.common import Item
    monkeypatch.setattr(common.requests, "get", _get_no_s2)
    hit = resolve.find_paper(_IdLLM({"match": 0, "confidence": 0.9, "why": "方法和数字一致"}),
                             Item(source="inbox", title="香农", url="u", text="x"))
    assert hit and hit["arxiv_id"] == "2610.77777"      # candidate list is sorted by title similarity


def test_resolve_rejects_low_confidence(monkeypatch):
    from pis import resolve
    from pis.common import Item
    monkeypatch.setattr(common.requests, "get", _get_no_s2)
    assert resolve.find_paper(_IdLLM({"match": 0, "confidence": 0.4}), Item(source="inbox", title="t", url="u", text="x")) is None


def test_resolve_openreview_pdf(monkeypatch):
    from pis import resolve
    from pis.common import Item

    def get(url, **kw):
        if "openreview" in url:
            return Resp(js={"notes": [{"forum": "abc", "content": {
                "title": {"value": "InfoTok: Information-Theoretic Adaptive Video Tokenization"},
                "abstract": {"value": "Adaptive Video Tokens via Information"}}}]})
        if "export.arxiv.org" in url:
            return Resp(b"<feed xmlns='http://www.w3.org/2005/Atom'></feed>")
        return Resp(js={"data": []})
    monkeypatch.setattr(common.requests, "get", get)
    hit = resolve.find_paper(_IdLLM(), Item(source="inbox", title="t", url="u", text="x"))
    assert hit == {"arxiv_id": None, "pdf_url": "https://openreview.net/pdf?id=abc",
                   "title": "InfoTok: Information-Theoretic Adaptive Video Tokenization"}


def test_canonical_wechat_url():
    from pis.web import canonical_url
    assert canonical_url("https://mp.weixin.qq.com/s/0Hz9v_KW-iv?from=singlemessage&scene=1") == "https://mp.weixin.qq.com/s/0Hz9v_KW-iv"
    assert canonical_url("https://arxiv.org/abs/2610.1?x=1") == "https://arxiv.org/abs/2610.1?x=1"


class InstantNotion(FakeNotion):
    """Day pages by title; Inbox rows split into unprocessed vs processed-instantly."""

    def __init__(self, pages=None, children_map=None, instant_rows=None):
        super().__init__()
        self.day_pages = dict(pages or {})
        self.kids = dict(children_map or {})
        self.instant_rows = instant_rows or []
        self.appended, self.inserted, self.deleted = [], [], []

    def find_child_page(self, parent, title):
        return self.day_pages.get(title)

    def children(self, bid):
        if bid in self.kids:
            return self.kids[bid]
        return super().children(bid)

    def create_page(self, parent, title, blocks, emoji="📰"):
        pid = super().create_page(parent, title, blocks, emoji)
        if parent == "pis":
            self.day_pages[title] = pid
            self.kids[pid] = [dict(b, id=f"{pid}-b{i}") for i, b in enumerate(blocks)]
        return pid

    def append(self, pid, blocks):
        check_blocks(blocks)
        self.appended.append((pid, blocks))

    def insert_after(self, pid, after, blocks):
        check_blocks(blocks)
        self.inserted.append((pid, after, blocks))

    def delete_block(self, bid):
        self.deleted.append(bid)

    def query_db(self, db, f=None, sorts=None):
        if db == "db" and f and "and" in f:
            return self.instant_rows
        return super().query_db(db, f, sorts)


def _instant_env(monkeypatch, tmp_path, fake, hour_utc=2):
    from datetime import datetime, timezone
    from pis import instant as I, main as M2
    monkeypatch.setattr(common.requests, "get", fake_get)
    monkeypatch.setattr(I, "LLM", FakeLLM)
    monkeypatch.setattr(I, "Notion", lambda *a, **k: fake)
    monkeypatch.setattr(I, "utcnow", lambda: datetime(2026, 10, 31, hour_utc, tzinfo=timezone.utc))
    monkeypatch.setattr(I, "ROOT", _root_copy(tmp_path))
    monkeypatch.setattr(M2, "ROOT", I.ROOT)
    for k, v in {"NOTION_TOKEN": "x", "NOTION_PIS_PAGE_ID": "pis", "DEEPSEEK_API_KEY": "k"}.items():
        monkeypatch.setenv(k, v)
    return I


def test_instant_goes_to_todays_page_before_the_digest(monkeypatch, tmp_path):
    fake = InstantNotion()
    I = _instant_env(monkeypatch, tmp_path, fake)
    assert I.run() == 0
    assert fake.day_pages == {"2026-10-31": "page-1"}                    # skeleton for today
    skel = fake.pages[0][2]
    assert skel[0]["type"] == "callout" and skel[0]["callout"]["rich_text"][0]["text"]["content"] == I.PLACEHOLDER
    pid, blocks = fake.appended[0]
    assert pid == "page-1" and [b["type"] for b in blocks] == ["to_do", "to_do"]
    kids = blocks[0]["to_do"]["children"]
    assert kids[0]["paragraph"]["rich_text"][0]["text"]["content"] == "一句话0"
    assert any(k["type"] == "link_to_page" for k in kids)
    rec = {p: props for p, props in fake.updated}
    assert rec["row1"]["Processed"]["checkbox"] and rec["row1"]["日期"]["date"]["start"] == "2026-10-31"
    assert rec["row2"]["类型"]["select"]["name"] == "开源项目" and "解析页" in rec["row2"]
    assert rec["row1"]["摘要"]["rich_text"][0]["text"]["content"] == "一句话0 细节0"


def test_instant_goes_to_tomorrow_after_the_digest(monkeypatch, tmp_path):
    filled = [{"id": "x", "type": "callout", "callout": {"rich_text": [{"plain_text": "PRH 成定理"}]}}]
    fake = InstantNotion(pages={"2026-10-31": "day-1031"}, children_map={"day-1031": filled})
    I = _instant_env(monkeypatch, tmp_path, fake, hour_utc=10)
    assert I.run() == 0
    assert fake.day_pages["2026-11-01"] == "page-1" and fake.appended[0][0] == "page-1"


def test_morning_run_fills_the_skeleton(monkeypatch, tmp_path):
    from pis import instant as I
    skeleton = [{"id": "ph", "type": "callout", "callout": {"rich_text": [{"plain_text": I.PLACEHOLDER}]}},
                {"id": "dv", "type": "divider", "divider": {}}]
    instant_row = {"id": "row9", "properties": {
        "Name": {"type": "title", "title": [{"plain_text": "提前收藏的论文"}]},
        "URL": {"type": "url", "url": "https://mp.weixin.qq.com/s/early"},
        "Note": {"type": "rich_text", "rich_text": [{"plain_text": "早上之前存的"}]},
        "摘要": {"type": "rich_text", "rich_text": [{"plain_text": "它做了 X"}]},
        "类型": {"type": "select", "select": {"name": "论文"}},
        "解析页": {"type": "url", "url": "https://www.notion.so/abc123"}}}
    fake = InstantNotion(pages={"2026-10-31": "day-1031"}, children_map={"day-1031": skeleton},
                         instant_rows=[instant_row])
    fake.kids["pis"] = fake.children_pis()
    monkeypatch.setattr(common.requests, "get", fake_get)
    monkeypatch.setattr(M, "LLM", FakeLLM)
    monkeypatch.setattr(M, "Notion", lambda *a, **k: fake)
    for k, v in {"NOTION_TOKEN": "x", "NOTION_PIS_PAGE_ID": "pis", "DEEPSEEK_API_KEY": "k"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(M, "ROOT", _root_copy(tmp_path))
    assert M.run(types.SimpleNamespace(dry_run=False, force=False, date="2026-10-31")) == 0

    assert [t for p, t, _ in fake.pages if p == "pis"] == []              # no new day page
    pid, after, blocks = fake.inserted[0]
    assert (pid, after) == ("day-1031", "ph") and blocks[0]["type"] == "callout"
    assert fake.deleted == ["ph"]
    subs = [t for p, t, _ in fake.pages if p == "day-1031"]
    assert "我的收藏（2）" in subs                                          # leftovers only; instant item is on the page
    table = next(b for b in blocks if b["type"] == "toggle" and "全部条目" in b["toggle"]["rich_text"][0]["text"]["content"])
    rows = table["toggle"]["children"][0]["table"]["children"]
    assert any("提前收藏的论文" in c[0]["text"]["content"] for r in rows for c in r["table_row"]["cells"][1:2])
    assert ("row9", {"已汇总": {"checkbox": True}}) in fake.updated


def test_page_text_reads_nested_blocks():
    from pis.notion import Notion
    tree = {
        "p": [{"id": "a", "type": "heading_2", "has_children": False, "heading_2": {"rich_text": [{"plain_text": "禁绝格式主义"}]}},
              {"id": "b", "type": "bulleted_list_item", "has_children": True,
               "bulleted_list_item": {"rich_text": [{"plain_text": "垃圾内容"}]}}],
        "b": [{"id": "c", "type": "bulleted_list_item", "has_children": False,
               "bulleted_list_item": {"rich_text": [{"plain_text": "不要加共识性内容"}]}}],
    }
    n = Notion.__new__(Notion)
    n.children = lambda bid: tree.get(bid, [])
    assert n.page_text("p") == "## 禁绝格式主义\n- 垃圾内容\n  - 不要加共识性内容"


def test_dedupe_skips_earlier_pushes_and_refills():
    from pis import memory, rank
    from pis.common import Item
    today = date(2026, 11, 14)
    mem = {"pushed": {"arxiv:old": "2026-11-13", "arxiv:today": "2026-11-14", "arxiv:expired": "2026-10-01"}}
    items = [Item(source="arxiv", title=k, url=k, key=f"arxiv:{k}", score=s)
             for k, s in [("old", 9), ("today", 9), ("expired", 9), ("new1", 8), ("new2", 7), ("low", 3)]]
    kept, dropped = memory.drop_pushed(items, mem, today, 30)
    assert dropped == 1 and [it.title for it in kept] == ["today", "expired", "new1", "new2", "low"]
    # yesterday's pick is gone and the next new candidate takes its slot; the score threshold still applies
    assert [it.title for it in rank.select(kept, 6, 3)] == ["today", "expired", "new1"]
    memory.mark_pushed(mem, rank.select(kept, 6, 3), today, 30)
    assert mem["pushed"] == {"arxiv:old": "2026-11-13", "arxiv:today": "2026-11-14",
                             "arxiv:expired": "2026-11-14", "arxiv:new1": "2026-11-14"}
