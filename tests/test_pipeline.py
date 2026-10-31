"""Offline end-to-end test: fake HTTP sources, fake DeepSeek, fake Notion."""
import json
import re
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
<h1 id="activity-name">公众号：Agent 评测新基准</h1><div id="js_content"><p>本文介绍了一个新的 Agent 评测基准，""" + "内容" * 50 + """</p></div></body></html>"""


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


def fake_get(url, **kw):
    if "rss.arxiv.org" in url:
        return Resp(ARXIV_RSS)
    if "daily_papers" in url:
        return Resp(js=HF if url.endswith("10-31") else [])
    if "mp.weixin.qq.com" in url:
        return Resp(text=WECHAT_HTML)
    if "fail" in url:
        return Resp(status=404)
    return Resp(blog_rss())


class FakeLLM:
    def __init__(self, *a, **k):
        self.model, self.usage = "fake", {"prompt_tokens": 1, "completion_tokens": 1}

    def json(self, system, user, **kw):
        body = user.split("# 待评分条目")[-1].split("# 今日条目")[-1]
        ids = [int(x) for x in re.findall(r"^\[(\d+)\]", body, re.M)]
        if "评分" in system:
            return {"results": [{"id": i, "score": 2 if "Cats" in body.split(f"[{i}]")[1][:80] else 8,
                                 "why": "命中 RL 推理"} for i in ids]}
        if "动态兴趣记忆" in system:
            assert "Agent 评测新基准" in user and "Old ticked paper" in user     # inbox + ticked are fed in
            return {"interests": [{"topic": "Agent 评测", "weight": 4, "trend": "up", "evidence": "收藏+勾选",
                                   "last_seen": "2026-10-31"}],
                    "threads": [{"name": "RLVR for agents", "summary": "GRPO 扩展到 agent", "last_seen": "2026-10-31"}],
                    "preferences": ["偏好有代码"], "notes": "从推理转向 agent 评测"}
        assert "动态记忆" in user and "RLVR for agents" in user                   # memory reaches the digest prompt
        return {"headline": "RLVR 走向 Agent", "takeaways": ["**GRPO** 用于 `Agent` [1]", "收藏 [4]"],
                "themes": [{"emoji": "🧠", "title": "推理", "body": "讨论 [1][4]，以及不存在的 [99]。",
                            "so_what": "可对比 [1]", "refs": [1, 2, 99], "key_ref": 1},
                           {"emoji": "🛠", "title": "工具", "body": "[3]", "refs": [3, 4], "key_ref": 42}],
                "threads": [{"name": "RLVR for agents", "update": "新进展 [1]"}],
                "items": [{"id": i, "tldr": f"要点{i}", "detail": "收藏总结" if i == ids[-1] else ""} for i in ids]}


def check_blocks(blocks, depth=0):
    """Notion API constraints: <=100 children/request, <=2 nesting levels, <=2000 chars & <=100 rich_text items."""
    assert depth <= 2, "nesting too deep"
    for b in blocks:
        data = b[b["type"]]
        rts = [data.get("rich_text", [])] + [c for r in data.get("cells", []) for c in [r]]
        for rt in rts:
            assert len(rt) <= 100 and all(len(t["text"]["content"]) <= 2000 for t in rt)
        kids = data.get("children", [])
        assert len(kids) <= 100
        if kids:
            check_blocks(kids, depth + 1)


MEM_JSON = json.dumps({"interests": [], "threads": [{"name": "RLVR for agents", "summary": "x", "last_seen": "2026-10-29"}],
                       "preferences": [], "notes": "", "recent_headlines": ["2026-10-30：昨天头条"], "feedback_seen": []})


class FakeNotion:
    def __init__(self, *a, **k):
        self.pages, self.updated, self.replaced = [], [], None

    def children_pis(self):
        return [{"id": "prof", "type": "child_page", "child_page": {"title": "🧭 研究画像"}},
                {"id": "mem", "type": "child_page", "child_page": {"title": "🧠 记忆"}},
                {"id": "db", "type": "child_database", "child_database": {"title": "📥 Inbox"}}]

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
        return "## 核心兴趣\n- reinforcement learning, reasoning, agents"

    def create_page(self, parent, title, blocks, emoji="📰"):
        check_blocks(blocks)
        json.dumps(blocks)  # must be serialisable
        self.pages.append((parent, title, blocks))
        return f"page-{len(self.pages)}"

    def query_db(self, db, f=None):
        return [{"id": "row1", "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "https://mp.weixin.qq.com/s/abc"}]},
            "URL": {"type": "url", "url": None},
            "Note": {"type": "rich_text", "rich_text": [{"plain_text": "想看评测设计"}]},
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
    assert titles == ["2026-10-31", "论文精选（2）", "动态与博客（1）", "我的收藏（1）"], titles
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
    assert mem["recent_headlines"][-1] == "2026-10-31：RLVR 走向 Agent"
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
            assert path == "/databases" and json["parent"]["page_id"] == "40ad4b61-755e-80b0-a159-f34c3f246739"
            created.append("db")
            return {"id": "new-db"}

    import yaml
    cfg = yaml.safe_load((root / "config" / "sources.yaml").read_text())
    ids = bootstrap.ensure(N0(), cfg, root)
    assert created == ["🧭 研究画像", "🧠 记忆", "db"] and ids["inbox"] == "new-db"


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
