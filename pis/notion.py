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
    def query_db(self, db_id: str, filter_: dict | None = None) -> list[dict]:
        out, cursor = [], None
        while True:
            body: dict = {"page_size": 100}
            if filter_:
                body["filter"] = filter_
            if cursor:
                body["start_cursor"] = cursor
            d = self.req("POST", f"/databases/{db_id}/query", json=body)
            out += d["results"]
            if not d.get("has_more"):
                return out
            cursor = d["next_cursor"]

    def update_props(self, page_id: str, props: dict) -> None:
        self.req("PATCH", f"/pages/{page_id}", json={"properties": props})


# ---- block builders --------------------------------------------------------
_CITE = re.compile(r"\[(\d+(?:\s*[,，]\s*\d+)*)\]")


def rich(text: str, *, link: str | None = None, bold: bool = False, color: str = "default") -> list[dict]:
    out = []
    for i in range(0, max(len(text), 1), MAX_TEXT):
        t: dict = {"type": "text", "text": {"content": text[i:i + MAX_TEXT]}}
        if link:
            t["text"]["link"] = {"url": link}
        if bold or color != "default":
            t["annotations"] = {"bold": bold, "color": color}
        out.append(t)
    return out


def rich_with_citations(text: str, links: dict[int, str]) -> list[dict]:
    """Turn '...见 [3][5] 或 [2, 4]' into text where each number links to the source URL."""
    out: list[dict] = []
    pos = 0
    for m in _CITE.finditer(text):
        if m.start() > pos:
            out += rich(text[pos:m.start()])
        nums = [int(n) for n in re.split(r"\s*[,，]\s*", m.group(1))]
        out += rich("[")
        for j, n in enumerate(nums):
            if j:
                out += rich(",")
            out += rich(str(n), link=links.get(n), color="blue") if n in links else rich(str(n))
        out += rich("]")
        pos = m.end()
    if pos < len(text):
        out += rich(text[pos:])
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


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}
