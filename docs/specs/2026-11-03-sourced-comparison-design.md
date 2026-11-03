# Sourced Comparison — Design

Date: 2026-11-03
Status: approved in session (user asked to implement all improvement ideas)
Scope: runtime external sources for the winner/runner-up comparison.

## 1. Problem

The comparison table shows price, score, condition and site, but it has no
external evidence. The user asked for comparisons backed by prepared
comparison pages or Bing/Google/search AI, with links and sources.

## 2. Verified facts

* DuckDuckGo's HTML endpoint (`https://html.duckduckgo.com/html/`) returns real
  result links with a normal Chrome user agent in this environment.
* Bing's RSS endpoint works but is heavily localized; for a niche 18650 query
  it returned Samsung phones instead of battery reviews. It is therefore only
  a fallback.
* The project already depends on `requests`; no new dependency is needed.
* `ResultProcessor` already builds a winner/runner-up comparison table and has
  `DealAnalysis.specs` available.

## 3. Goals

* G1 — For the winner and runner-ups, search the web for spec/review pages.
* G2 — Show a numbered `## Sources` section with real URLs and snippets.
* G3 — Add a deterministic `Why the winner won` line backed by the score,
  effective price, condition and the number of external sources.
* G4 — Never invent a source; if the search fails or returns nothing, omit the
  section.
* G5 — The test suite must not hit the network.

## 4. Non-goals

* LLM-written claims without a matching source.
* Paid search APIs, Google Custom Search keys or browser scraping of Google.
* Fetching and parsing the full content of every source page.
* Source credibility scoring.

## 5. Source provider

`src/research/web_search.py`:

```python
@dataclass(frozen=True)
class WebSource:
    title: str
    url: str
    snippet: str = ""

def search_web(query: str, max_results: int = 5, timeout: float = 15.0) -> list[WebSource]
def comparison_query(title: str) -> str
```

* DuckDuckGo HTML first; decode its `uddg` redirect links.
* Bing RSS fallback if DuckDuckGo fails or returns no results.
* Deduplicate by URL and cap at `max_results`.
* Catch request/parse errors and return `[]`; a failed source search never
  breaks a report.

## 6. Report

After `## Comparison`, when at least two top deals exist:

```markdown
**Why the winner won:** score 76/100, effective price 1.85 EUR,
condition unknown, 3 external source(s).

## Sources

1. [Samsung INR18650-30Q In-Depth Review](https://...) — for *Samsung ...*
2. ...
```

The source list is per top product (winner + runner-ups), deduplicated. If the
provider returns nothing, neither the line nor the section is printed.

## 7. Configuration

`SearchConfig` gains:

```python
sources: bool = True
source_count: int = 5
```

`config.example.yaml` and `config.yaml` set both explicitly. Setting
`sources: false` disables the network calls.

## 8. Testing

* DuckDuckGo HTML parser decodes redirect URLs, strips tags, deduplicates.
* Bing RSS fallback works when DuckDuckGo returns nothing.
* Request failure returns `[]`.
* `comparison_query` includes the listing title and `specs review`.
* `ResultProcessor` prints `## Sources` and the winner line when a fake provider
  returns a source; omits both when it returns nothing.
* An autouse fixture in `tests/conftest.py` replaces `search_web` with a no-op
  so the ordinary suite never touches the network.

## 9. Risks

* Search engines can rate-limit or change HTML. DuckDuckGo is first, Bing RSS is
  the fallback, and both fail softly.
* Source quality varies. The report links the page and snippet; it does not
  claim the source agrees with the winner.
* Three searches per report add latency. `source_count` and the top-three cap
  bound the work.
