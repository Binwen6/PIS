"""Fetch a web page and extract readable title + text (special-cases 微信公众号)."""
from __future__ import annotations

from bs4 import BeautifulSoup

from .common import http_get, log


def extract(html: str, url: str = "") -> tuple[str, str]:
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
    return title, text


def fetch_text(url: str, limit: int = 4000) -> tuple[str, str]:
    try:
        r = http_get(url, timeout=30, retries=2)
        if r.status_code != 200:
            return "", ""
        r.encoding = r.apparent_encoding or r.encoding
        title, text = extract(r.text, url)
        return title, text[:limit]
    except Exception as e:  # noqa: BLE001
        log.warning("fetch %s failed: %s", url, e)
        return "", ""
