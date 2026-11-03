"""Bing RSS and DuckDuckGo source parsing (offline)."""

from src.research import web_search


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise web_search.requests.HTTPError("bad status")  # noqa: TRY003


RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss><channel>
<item>
  <title>Battery review &amp; test</title>
  <link>https://example.com/review</link>
  <description>&lt;b&gt;Capacity&lt;/b&gt; and current test</description>
</item>
<item>
  <title>Duplicate</title>
  <link>https://example.com/review</link>
  <description>duplicate</description>
</item>
<item>
  <title>Second source</title>
  <link>https://example.org/specs</link>
  <description>Specs page</description>
</item>
</channel></rss>
"""

DDG_HTML = """
<a rel="nofollow" class="result__a"
   href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Freview">
  Battery review &amp; test
</a>
<a class="result__snippet">Capacity and current test</a>
<a rel="nofollow" class="result__a"
   href="https://example.org/specs">Second source</a>
<a class="result__snippet">Specs page</a>
"""


class FakeHtmlResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise web_search.requests.HTTPError("bad status")  # noqa: TRY003


def test_search_web_uses_duckduckgo_first(monkeypatch):
    monkeypatch.setattr(
        web_search.requests,
        "get",
        lambda *args, **kwargs: FakeHtmlResponse(DDG_HTML),
    )

    sources = web_search.search_web("18650 review", max_results=5)

    assert [source.url for source in sources] == [
        "https://example.com/review",
        "https://example.org/specs",
    ]
    assert sources[0].title == "Battery review & test"
    assert "Capacity" in sources[0].snippet



def test_search_web_falls_back_to_bing_rss(monkeypatch):
    def fake_get(url, *args, **kwargs):
        if "duckduckgo" in url:
            return FakeHtmlResponse("", 200)
        return FakeResponse(RSS)

    monkeypatch.setattr(web_search.requests, "get", fake_get)

    sources = web_search.search_web("18650 review", max_results=5)

    assert [source.url for source in sources] == [
        "https://example.com/review",
        "https://example.org/specs",
    ]
    assert sources[0].title == "Battery review & test"
    assert "Capacity" in sources[0].snippet


def test_search_web_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(
        web_search.requests, "get", lambda *args, **kwargs: FakeHtmlResponse("", 500)
    )
    assert web_search.search_web("x") == []


def test_comparison_query_mentions_specs_and_review():
    query = web_search.comparison_query("Samsung INR18650-30Q 3000mAh")
    assert "Samsung INR18650-30Q" in query
    assert "specs review" in query
