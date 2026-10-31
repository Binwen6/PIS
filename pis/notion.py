"""Minimal Notion REST client + block builders."""
from __future__ import annotations

import os
import re
import time

import requests

from .common import log

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
MAX_TEXT = 1900          # Notion limit is 2000 chars per rich_text object


class Notion:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ["NOTION_TOKEN"]
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": VERSION,
            "Content-Type": "application/json",
        })

    def req(self, method: str, path: str, **kw) -> dict:
        for i in range(5):
            r = self.s.request(method, API + path, timeout=60, **kw)
            if r.status_code in (429, 502, 503, 504):
                time.sleep(float(r.headers.get("Retry-After", 2 ** i)))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"Notion {method} {path} -> {r.status_code}: {r.text[:500]}")
            return r.json()
        raise RuntimeError(f"Notion {method} {path}: retries exhausted")

    # ---- pages / blocks -------------------------------------------------
    def children(self, block_id: str) -> list[dict]:
        out, cursor = [], None
        while True:
            q = f"?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
            d = self.req("GET", f"/blocks/{block_id}/children{q}")
            out += d["results"]
            if not d.get("has_more"):
                return out
            cursor = d["next_cursor"]

    def find_child_page(self, parent_id: str, title: str) -> str | None:
        for b in self.children(parent_id):
            if b["type"] == "child_page" and b["child_page"]["title"] == title:
                return b["id"]
        return None

    def create_page(self, parent_id: str, title: str, blocks: list[dict], emoji: str = "📰") -> str:
        page = self.req("POST", "/pages", json={
            "parent": {"page_id": parent_id},
            "icon": {"type": "emoji", "emoji": emoji},
            "properties": {"title": {"title": [{"text": {"content": title}}]}},
            "children": blocks[:100],
        })
        self.append(page["id"], blocks[100:])
        return page["id"]

    def append(self, block_id: str, blocks: list[dict]) -> None:
        for i in range(0, len(blocks), 100):
            self.req("PATCH", f"/blocks/{block_id}/children", json={"children": blocks[i:i + 100]})

    def delete_block(self, block_id: str) -> None:
        self.req("DELETE", f"/blocks/{block_id}")

    def replace_content(self, page_id: str, blocks: list[dict]) -> None:
        for b in self.children(page_id):
            if b["type"] not in ("child_page", "child_database"):
                self.delete_block(b["id"])
        self.append(page_id, blocks)

    def archive(self, page_id: str) -> None:
        self.req("PATCH", f"/pages/{page_id}", json={"archived": True})

    def page_text(self, page_id: str) -> str:
        """Plain text of a page (used to read the editable research profile)."""
        lines = []
        for b in self.children(page_id):
            data = b.get(b["type"], {})
            rt = data.get("rich_text")
            if rt is not None:
                prefix = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
                          "bulleted_list_item": "- ", "numbered_list_item": "- ", "to_do": "- "}.get(b["type"], "")
                lines.append(prefix + "".join(t.get("plain_text", "") for t in rt))
        return "\n".join(lines).strip()

    # ---- databases ------------------------------------------------------
    def query_db(self, db_id: str, filter_: dict | None = None, sorts: list | None = None) -> list[dict]:
        out, cursor = [], None
        while True:
            body: dict = {"page_size": 100}
            if filter_:
                body["filter"] = filter_
            if sorts:
                body["sorts"] = sorts
            if cursor:
                body["start_cursor"] = cursor
            d = self.req("POST", f"/databases/{db_id}/query", json=body)
            out += d["results"]
            if not d.get("has_more"):
                return out
            cursor = d["next_cursor"]

    def create_db_page(self, db_id: str, props: dict, blocks: list[dict], emoji: str = "📄") -> str:
        page = self.req("POST", "/pages", json={
            "parent": {"database_id": db_id},
            "icon": {"type": "emoji", "emoji": emoji},
            "properties": props,
            "children": blocks[:100],
        })
        self.append(page["id"], blocks[100:])
        return page["id"]

    def update_props(self, page_id: str, props: dict) -> None:
        self.req("PATCH", f"/pages/{page_id}", json={"properties": props})


# ---- block builders --------------------------------------------------------
_CITE = re.compile(r"\[(\d+(?:\s*[,，]\s*\d+)*)\]")
# inline syntax the LLM may use: **bold**, `code`, [3] / [2,5] citations, $latex$
_INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|\[(\d+(?:\s*[,，]\s*\d+)*)\]|(?<![\$\\])\$([^$\n]+?)\$(?!\$)")


def rich(text: str, *, link: str | None = None, bold: bool = False, color: str = "default",
         code: bool = False, italic: bool = False) -> list[dict]:
    out = []
    for i in range(0, max(len(text), 1), MAX_TEXT):
        t: dict = {"type": "text", "text": {"content": text[i:i + MAX_TEXT]}}
        if link:
            t["text"]["link"] = {"url": link}
        if bold or code or italic or color != "default":
            t["annotations"] = {"bold": bold, "code": code, "italic": italic, "color": color}
        out.append(t)
    return out


def rich_with_citations(text: str, links: dict[int, str], color: str = "default") -> list[dict]:
    """Inline-markdown -> rich text. '[3][5]' / '[2, 4]' become links to the sources."""
    out: list[dict] = []
    pos = 0
    for m in _INLINE.finditer(text or ""):
        if m.start() > pos:
            out += rich(text[pos:m.start()], color=color)
        if m.group(1):
            out += rich(m.group(1), bold=True, color=color)
        elif m.group(2):
            out += rich(m.group(2), code=True)
        elif m.group(4):
            out.append({"type": "equation", "equation": {"expression": m.group(4).strip()[:1000]}})
        else:
            nums = [int(n) for n in re.split(r"\s*[,，]\s*", m.group(3))]
            out += rich("[", color=color)
            for j, n in enumerate(nums):
                if j:
                    out += rich(",", color=color)
                out += rich(str(n), link=links.get(n), color="blue", bold=True) if n in links else rich(str(n))
            out += rich("]", color=color)
        pos = m.end()
    if pos < len(text or ""):
        out += rich(text[pos:], color=color)
    return out[:100]   # Notion: max 100 rich_text objects per block


def _block(kind: str, rt: list[dict], **extra) -> dict:
    return {"object": "block", "type": kind, kind: {"rich_text": rt, **extra}}


def heading(text: str, level: int = 2) -> dict:
    return _block(f"heading_{level}", rich(text))


def paragraph(rt: list[dict]) -> dict:
    return _block("paragraph", rt)


def bullet(rt: list[dict], children: list[dict] | None = None) -> dict:
    b = _block("bulleted_list_item", rt)
    if children:
        b["bulleted_list_item"]["children"] = children
    return b


def callout(rt: list[dict], emoji: str = "💡", color: str = "gray_background") -> dict:
    return _block("callout", rt, icon={"type": "emoji", "emoji": emoji}, color=color)


def toggle(rt: list[dict], children: list[dict]) -> dict:
    return _block("toggle", rt, children=children)


def todo(rt: list[dict], children: list[dict] | None = None, checked: bool = False) -> dict:
    b = _block("to_do", rt, checked=checked)
    if children:
        b["to_do"]["children"] = children
    return b


def quote(rt: list[dict], color: str = "default") -> dict:
    return _block("quote", rt, color=color)


def code(text: str, language: str = "plain text") -> dict:
    return _block("code", rich(text), language=language)


def bookmark(url: str) -> dict:
    return {"object": "block", "type": "bookmark", "bookmark": {"url": url}}


def image(url: str) -> dict:
    return {"object": "block", "type": "image", "image": {"type": "external", "external": {"url": url}}}


def toc() -> dict:
    return {"object": "block", "type": "table_of_contents", "table_of_contents": {"color": "gray"}}


def table(header: list[str], rows: list[list[list[dict]]]) -> dict:
    def row(cells):
        return {"object": "block", "type": "table_row", "table_row": {"cells": cells}}
    return {"object": "block", "type": "table", "table": {
        "table_width": len(header), "has_column_header": True, "has_row_header": False,
        "children": [row([rich(h, bold=True) for h in header])] + [row(r) for r in rows][:99]}}


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def equation(expr: str) -> dict:
    return {"object": "block", "type": "equation", "equation": {"expression": expr.strip()[:1000]}}


def link_to_page(page_id: str) -> dict:
    return {"object": "block", "type": "link_to_page", "link_to_page": {"type": "page_id", "page_id": page_id}}


def numbered(rt: list[dict]) -> dict:
    return _block("numbered_list_item", rt)


_NUM = re.compile(r"^\d+[.)、]\s+")


def md_to_blocks(md: str) -> list[dict]:
    """Small Markdown -> Notion converter for LLM-written long-form text.

    Supports #/##/### headings, paragraphs, - / 1. lists, > quotes, ---, ``` code fences,
    $$ display math $$ (single- or multi-line) and inline **bold** / `code` / $math$.
    """
    inline = lambda t: rich_with_citations(t, {})  # noqa: E731
    blocks: list[dict] = []
    para: list[str] = []

    def flush():
        if para:
            blocks.append(paragraph(inline(" ".join(para))))
            para.clear()

    lines = (md or "").splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if s.startswith("```"):
            flush()
            lang, buf = s[3:].strip() or "plain text", []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            blocks.append(code("\n".join(buf), lang if lang in ("python", "mermaid", "json", "bash", "latex") else "plain text"))
        elif s.startswith("$$"):
            flush()
            body = s[2:]
            if body.endswith("$$") and len(body) >= 2:
                expr = body[:-2]
            else:
                buf = [body]
                i += 1
                while i < len(lines) and not lines[i].strip().endswith("$$"):
                    buf.append(lines[i])
                    i += 1
                if i < len(lines):
                    buf.append(lines[i].strip()[:-2])
                expr = "\n".join(buf)
            if expr.strip():
                blocks.append(equation(expr))
        elif not s:
            flush()
        elif s.startswith("#"):
            flush()
            level = min(max(len(s) - len(s.lstrip("#")), 2), 3)   # '#' -> h2, '###+' -> h3
            blocks.append(_block(f"heading_{level}", inline(s.lstrip("#").strip())))
        elif s in ("---", "***", "___"):
            flush()
            blocks.append(divider())
        elif s.startswith(("- ", "* ", "• ")):
            flush()
            blocks.append(bullet(inline(s[2:].strip())))
        elif _NUM.match(s):
            flush()
            blocks.append(numbered(inline(_NUM.sub("", s))))
        elif s.startswith(">"):
            flush()
            blocks.append(quote(inline(s.lstrip("> ").strip())))
        else:
            para.append(s)
        i += 1
    flush()
    return blocks
