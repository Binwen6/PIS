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
        ids = [int(x) for x in re.findall(r"^\[(\d+)\]", user, re.M)]
        if "评分" in system:
            return {"results": [{"id": i, "score": 2 if "Cats" in user.split(f"[{i}]")[1][:80] else 8,
                                 "why": "命中 RL 推理"} for i in ids]}
        return {"headline": "RLVR 走向 Agent", "overview": "今天 GRPO 用到了 Agent 上 [1]，另见 [2, 3] 与收藏 [5]。",
                "themes": [{"title": "推理", "body": "讨论 [1][4]，以及不存在的 [99]。"}],
                "items": [{"id": i, "tldr": f"要点{i}", "detail": "收藏总结" if i == ids[-1] else ""} for i in ids]}


class FakeNotion:
    def __init__(self, *a, **k):
        self.pages, self.updated = [], []

    def find_child_page(self, parent, title):
        return None

    def page_text(self, pid):
        return "## 核心兴趣\n- reinforcement learning, reasoning, agents"

    def create_page(self, parent, title, blocks, emoji="📰"):
        assert all(len(t["text"]["content"]) <= 2000 for b in blocks for t in b[b["type"]].get("rich_text", []))
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
    for k, v in {"NOTION_TOKEN": "x", "NOTION_PIS_PAGE_ID": "pis", "NOTION_INBOX_DB_ID": "db",
                 "NOTION_PROFILE_PAGE_ID": "prof", "DEEPSEEK_API_KEY": "k"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(M, "ROOT", _root_copy(tmp_path))
    args = types.SimpleNamespace(dry_run=False, force=False, date="2026-10-31")
    assert M.run(args) == 0

    titles = [t for _, t, _ in fake.pages]
    assert titles[0] == "2026-10-31"
    assert any(t.startswith("📄 论文精选（2）") for t in titles), titles      # cat paper filtered out, HF-only added
    assert any(t.startswith("🌐 动态与博客（1）") for t in titles), titles     # old blog post filtered by window
    assert any(t.startswith("📌 我的收藏（1）") for t in titles), titles
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
