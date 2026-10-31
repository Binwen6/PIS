"""Fetch a web page and extract readable title + text (special-cases 微信公众号)."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .common import http_get, log


_ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})|arXiv[:：\s]\s*(\d{4}\.\d{4,5})", re.I)


def arxiv_id_in(html: str) -> str:
    m = _ARXIV.search(html or "")
    return (m.group(1) or m.group(2)) if m else ""


_GH = re.compile(r"github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9_.-]{1,100})")
_GH_NOISE = {"features", "topics", "orgs", "settings", "about", "pricing", "login", "sponsors", "marketplace", "apps"}


def github_repo_in(html: str) -> str:
    """Most frequently linked owner/repo in the page, if any."""
    counts: dict[str, int] = {}
    for o, r in _GH.findall(html or ""):
        r = re.sub(r"\.git$", "", r).rstrip(".")
        if o.lower() in _GH_NOISE or not r:
            continue
        counts[f"{o}/{r}"] = counts.get(f"{o}/{r}", 0) + 1
    return max(counts, key=counts.get) if counts else ""


def extract(html: str, url: str = "") -> tuple[str, str, str]:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        t.decompose()

    def meta(prop: str) -> str:
        m = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return (m.get("content") or "").strip() if m else ""

    title = meta("og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    if "mp.weixin.qq.com" in url:
        node = soup.select_one("#js_content")
        h = soup.select_one("#activity-name")
        if h:
            title = h.get_text(strip=True)
    else:
        node = soup.find("article") or soup.find("main") or soup.body
    text = node.get_text(" ", strip=True) if node else ""
    if len(text) < 80:                      # JS-rendered page (小红书/知乎 often) -> fall back to description
        text = meta("og:description") or meta("description") or text
    img = meta("og:image")
    if not img.startswith("https://") or "qpic.cn" in img or "weixin" in img:
        img = ""                     # 公众号图床有防盗链，在 Notion 中会显示为“未经允许不可引用”
    return title, text, img


def fetch_text(url: str, limit: int = 4000) -> tuple[str, str, str, str, str]:
    """-> (title, text, og_image, arxiv_id, github owner/repo)"""
    try:
        r = http_get(url, timeout=30, retries=2)
        if r.status_code != 200:
            return "", "", "", "", ""
        r.encoding = r.apparent_encoding or r.encoding
        title, text, img = extract(r.text, url)
        return title, text[:limit], img, arxiv_id_in(r.text), github_repo_in(r.text)
    except Exception as e:  # noqa: BLE001
        log.warning("fetch %s failed: %s", url, e)
        return "", "", "", "", ""
