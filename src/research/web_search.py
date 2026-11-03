"""Runtime web search used to attach external sources to a comparison.

DuckDuckGo's HTML endpoint returns real result links without an API key. Bing
RSS is kept as a fallback. A failed search is not an error: the report simply
omits the sources section.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree

import requests

logger = logging.getLogger(__name__)

DUCKDUCKGO_HTML = "https://html.duckduckgo.com/html/"
BING_RSS = "https://www.bing.com/search"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class WebSource:
    """One external page that supports a comparison."""

    title: str
    url: str
    snippet: str = ""

    def as_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


def _clean(text: str) -> str:
    return " ".join(html.unescape(_TAG_RE.sub(" ", text or "")).split())


class _DuckDuckGoParser(HTMLParser):
    """Collect result anchors and snippets in document order."""

    def __init__(self):
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self.snippets: list[str] = []
        self._href: str | None = None
        self._title: list[str] = []
        self._snippet: list[str] = []
        self._in_snippet = False

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attributes = dict(attrs)
        classes = attributes.get("class", "")
        if "result__a" in classes:
            self._href = attributes.get("href", "")
            self._title = []
        elif "result__snippet" in classes:
            self._in_snippet = True
            self._snippet = []

    def handle_data(self, data):
        if self._href is not None:
            self._title.append(data)
        if self._in_snippet:
            self._snippet.append(data)

    def handle_endtag(self, tag):
        if tag != "a":
            return
        if self._href is not None:
            self.anchors.append((" ".join(self._title), self._href))
            self._href = None
        if self._in_snippet:
            self.snippets.append(" ".join(self._snippet))
            self._in_snippet = False


def _decode_ddg_url(href: str) -> str:
    href = (href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


def _parse_duckduckgo(html_text: str) -> list[WebSource]:
    parser = _DuckDuckGoParser()
    try:
        parser.feed(html_text)
    except Exception:  # noqa: BLE001 - malformed HTML must not break a report
        return []
    sources: list[WebSource] = []
    for index, (title, href) in enumerate(parser.anchors):
        url = _decode_ddg_url(href)
        if not url.startswith(("http://", "https://")):
            continue
        snippet = parser.snippets[index] if index < len(parser.snippets) else ""
        sources.append(
            WebSource(title=_clean(title), url=url, snippet=_clean(snippet))
        )
    return sources


def _search_duckduckgo(query: str, timeout: float) -> list[WebSource]:
    response = requests.get(
        DUCKDUCKGO_HTML,
        params={"q": query},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return _parse_duckduckgo(response.text)


def _search_bing_rss(query: str, timeout: float) -> list[WebSource]:
    response = requests.get(
        BING_RSS,
        params={"format": "rss", "q": query},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)  # noqa: S314 - Bing RSS, bounded response
    sources: list[WebSource] = []
    for item in root.findall(".//item"):
        url = (item.findtext("link") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        title = _clean(item.findtext("title") or "")
        if not title:
            continue
        sources.append(
            WebSource(
                title=title,
                url=url,
                snippet=_clean(item.findtext("description") or ""),
            )
        )
    return sources


def _dedupe(sources: list[WebSource], max_results: int) -> list[WebSource]:
    seen: set[str] = set()
    out: list[WebSource] = []
    for source in sources:
        if source.url in seen:
            continue
        seen.add(source.url)
        out.append(source)
        if len(out) >= max_results:
            break
    return out


def search_web(query: str, max_results: int = 5, timeout: float = 15.0) -> list[WebSource]:
    """Search DuckDuckGo HTML, falling back to Bing RSS.

    The caller treats an empty list as "no external sources"; network and parse
    failures are logged at debug level and never break a report.
    """
    if not query or max_results <= 0:
        return []
    try:
        sources = _search_duckduckgo(query, timeout)
        if sources:
            return _dedupe(sources, max_results)
    except (requests.RequestException, ValueError) as exc:
        logger.debug("DuckDuckGo search failed for %r: %s", query, exc)

    try:
        return _dedupe(_search_bing_rss(query, timeout), max_results)
    except (requests.RequestException, ElementTree.ParseError, ValueError) as exc:
        logger.debug("Bing RSS search failed for %r: %s", query, exc)
        return []


def comparison_query(title: str) -> str:
    """Build a review/spec query from a listing title."""
    cleaned = " ".join((title or "").split())[:140]
    return f"{cleaned} specs review"


__all__ = ["WebSource", "comparison_query", "search_web"]
