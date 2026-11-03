# Site Catalog and Unlimited Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the LLM select every suitable shop with no count cap, let the user name shops explicitly, add Amazon/eBay/nkon/ecoprodukt/Solaro/Nay to the catalogue, and load saved cookie sessions before searching.

**Architecture:** The registry gains notes and specialty keywords; `SiteSelector` stops capping and receives the full runnable candidate list. `PlaywrightSearcher` enforces runnable status, resolves `--sites`, caches once per original prompt, applies per-site cookie sessions, and exposes a `SitePlan` for the report. New adapters/profiles cover Amazon, eBay quotes, nkon, ecoprodukt and Nay.

**Tech Stack:** Python 3.11+, Playwright, pydantic config models, Typer CLI, pytest, existing `ProfileAdapter`, existing `PriceQuote` helpers, no new dependency.

**Spec:** `docs/specs/2026-11-03-site-catalog-selection-design.md`

## Global Constraints

- `max_sites = 0` or `None` means **unlimited**; a positive value keeps the old cap.
- The `ask` wizard must not ask for a shop count.
- `--sites` is authoritative: it bypasses the LLM; unknown names raise `ValueError`.
- The LLM may only return ids from the runnable candidate list.
- `blocked` and `planned` sites are never runnable. `needs_login` is runnable without a session only when explicitly requested.
- A valid LLM response with an empty `selected` list means "no suitable shop"; malformed JSON/timeouts fall back to all candidates.
- Session files live under `data/sessions/` (already git-ignored); no credentials in the repository.
- Existing `Deal`, `price_eur` and report consumers must keep working.
- Full suite baseline before this plan: **576 passed, 11 skipped**.
- No new third-party dependency.

## Review Focus

- `--sites solaro_sk` must skip with "blocked", not open a Cloudflare page or silently return nothing.
- `max_sites=0` must select all candidates, not fall back to `8` through an `or` expression.
- A valid empty LLM selection must produce zero shops; a broken LLM must fall back to all shops.
- A missing or malformed `data/sessions/<site>.json` must not crash a run.
- A site whose profile is still `draft` or whose registry status is `planned` must never be opened.

---

### Task 1: Catalogue metadata, specialties and config entries

**Files:**
- Modify: `src/searcher/site_registry.py`
- Modify: `src/searcher/site_selection.py`
- Modify: `config.yaml`
- Modify: `config.example.yaml`
- Modify: `tests/test_site_registry.py`
- Modify: `tests/test_config_example.py`

**Interfaces:**
- Produces: `SiteSpec.notes: str = ""`, `SiteSpec.specialties: tuple[str, ...] = ()`
- Produces: `SiteCandidate.notes: str = ""`, `SiteCandidate.specialties: tuple[str, ...] = ()`
- Produces registry ids: `nkon_nl`, `ecoprodukt_sk`, `solaro_sk`
- Keeps statuses honest at this stage: `amazon_de` planned, `ebay` needs_login, `nay` planned, nkon/ecoprodukt planned, solaro blocked.

- [ ] **Step 1: Write the failing tests**

In `tests/test_site_registry.py`:

```python
def test_specialty_sites_are_registered():
    ids = {s.id for s in SITES}
    assert {"nkon_nl", "ecoprodukt_sk", "solaro_sk"} <= ids


def test_specialties_are_lowercase_keywords():
    for site in SITES:
        assert all(value == value.lower() for value in site.specialties), site.id


def test_new_sites_have_honest_status():
    assert by_id("nkon_nl").status == "planned"
    assert by_id("ecoprodukt_sk").status == "planned"
    assert by_id("solaro_sk").status == "blocked"


def test_new_specialty_sites_declare_their_niche():
    assert "battery" in by_id("nkon_nl").specialties
    assert "solar" in by_id("ecoprodukt_sk").specialties
    assert "solar" in by_id("solaro_sk").specialties
```

Update `test_summary_counts` to the new totals:

```python
def test_summary_counts():
    s = summary()
    assert s["working"] == 2
    assert s["blocked"] == 4
    assert s["needs_login"] == 2
    assert s["planned"] == 25
    assert sum(s.values()) == len(SITES)
```

Update `test_condition_filter` so the refurbished set includes `nkon_nl`:

```python
def test_condition_filter():
    refurbished = sites_for("electronics", "refurbished")
    assert {s.id for s in refurbished} == {
        "backmarket", "ebay", "heureka", "idealo", "amazon_de", "aukro",
        "nkon_nl",
    }
```

In `tests/test_config_example.py`, replace the hardcoded enabled list:

```python
def test_example_config_only_enables_verified_sites():
    from src.searcher.site_registry import by_status

    enabled = {name for name, site in _example_sites().items() if site.get("enabled")}
    assert enabled == {site.id for site in by_status("working")}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_site_registry.py tests/test_config_example.py -q
```

Expected: FAIL on missing ids/fields and on the new summary counts.

- [ ] **Step 3: Implement the model and registry entries**

Add to `SiteSpec`:

```python
notes: str = ""
specialties: tuple[str, ...] = ()
```

`notes` already exists on `SiteSpec`; keep it. Add `specialties` after `notes`.

Add to `SiteCandidate`:

```python
notes: str = ""
specialties: tuple[str, ...] = ()
```

Add registry entries:

```python
SiteSpec("nkon_nl", "NKON.nl", "https://www.nkon.nl", "nkon_nl",
         ("electronics", "hobby"), ("new", "used", "refurbished"), "planned",
         seller_type="retailer", has_warranty=False,
         warranty_note="Used cells carry the seller warranty; check each listing.",
         notes="Magento battery specialist. Search: /en/catalogsearch/result/?q=.",
         specialties=("battery", "18650", "lifepo4", "charger", "used"),
         country="NL", currency="EUR"),
SiteSpec("ecoprodukt_sk", "Ecoprodukt.sk", "https://ecoprodukt.sk", "ecoprodukt_sk",
         ("electronics", "home", "hobby"), ("new", "used", "open_box"), "planned",
         seller_type="retailer", has_warranty=True,
         warranty_note="Retailer warranty; used/open-box terms vary by listing.",
         notes="WooCommerce photovoltaics and batteries; has a used/open-box section.",
         specialties=("solar", "photovoltaic", "battery", "inverter", "used", "open_box"),
         country="SK", currency="EUR"),
SiteSpec("solaro_sk", "Solaro.sk", "https://solaro.sk", "solaro_sk",
         ("electronics", "home", "hobby"), ("new",), "blocked",
         seller_type="retailer", has_warranty=True,
         warranty_note="Retailer warranty on new items.",
         notes="Cloudflare challenge blocks automated sessions; needs a real session.",
         specialties=("solar", "photovoltaic", "battery", "inverter"),
         country="SK", currency="EUR"),
```

Update existing entries:

* `amazon_de`: add `specialties=("marketplace", "broad")`; keep `planned` until Task 6.
* `ebay`: add `specialties=("marketplace", "used", "refurbished")` and change the
  status to `needs_login` now (the live check already shows a 403).
* `nay`: add `specialties=("electronics", "retailer")`; keep `planned` until Task 8.

Use `NL` for nkon's country and `EUR`; the existing `test_every_site_has_a_country_and_currency` allows it.

- [ ] **Step 4: Add config entries**

In both `config.yaml` and `config.example.yaml`, add disabled entries:

```yaml
    - name: "nkon_nl"
      base_url: "https://www.nkon.nl"
      enabled: false
      adapter_class: "nkon_nl"
      categories: ["electronics", "hobby"]
      conditions: ["new", "used", "refurbished"]
      country: "NL"
      currency: "EUR"
    - name: "ecoprodukt_sk"
      base_url: "https://ecoprodukt.sk"
      enabled: false
      adapter_class: "ecoprodukt_sk"
      categories: ["electronics", "home", "hobby"]
      conditions: ["new", "used", "open_box"]
      country: "SK"
      currency: "EUR"
    - name: "solaro_sk"
      base_url: "https://solaro.sk"
      enabled: false
      adapter_class: "solaro_sk"
      categories: ["electronics", "home", "hobby"]
      conditions: ["new"]
      country: "SK"
      currency: "EUR"
```

Keep `amazon_de`, `ebay` and `nay` disabled in `config.example.yaml` for now; `config.yaml` may stay disabled until their task.

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_site_registry.py tests/test_config_example.py tests/test_site_selection.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/searcher/site_registry.py src/searcher/site_selection.py config.yaml config.example.yaml tests/test_site_registry.py tests/test_config_example.py
git commit -m "feat(catalog): add specialty site metadata and entries"
```

---

### Task 2: Cookie sessions and login support

**Files:**
- Create: `src/searcher/sessions.py`
- Modify: `scripts/login.py`
- Modify: `src/searcher/playwright_searcher.py`
- Modify: `src/cli/app.py`
- Modify: `config.yaml`, `config.example.yaml` (`browser.login_sites`)
- Create: `tests/test_sessions.py`

**Interfaces:**
- Produces: `SESSION_DIR: Path`
- Produces: `session_path(site_id: str) -> Path`
- Produces: `has_session(site_id: str) -> bool`
- Produces: `load_cookies(site_id: str) -> list[dict]`
- Produces: `async def apply_session(context, site_id: str) -> bool`
- Produces: `site_base_url(site_id: str) -> str` in `scripts/login.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sessions.py`:

```python
import json

import pytest

from src.searcher import sessions


def test_missing_session_file_is_false(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    assert sessions.has_session("ebay") is False
    assert sessions.load_cookies("ebay") == []


def test_load_cookies_reads_the_saved_list(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    (tmp_path / "ebay.json").write_text(
        json.dumps([{"name": "sid", "value": "x", "domain": ".ebay.de", "path": "/"}]),
        encoding="utf-8",
    )
    assert sessions.has_session("ebay") is True
    assert sessions.load_cookies("ebay")[0]["name"] == "sid"


def test_malformed_session_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    (tmp_path / "ebay.json").write_text("{broken", encoding="utf-8")
    assert sessions.load_cookies("ebay") == []


@pytest.mark.asyncio
async def test_apply_session_adds_cookies(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    (tmp_path / "ebay.json").write_text(
        json.dumps([{"name": "sid", "value": "x", "domain": ".ebay.de", "path": "/"}]),
        encoding="utf-8",
    )

    class FakeContext:
        def __init__(self):
            self.cookies = None

        async def add_cookies(self, cookies):
            self.cookies = cookies

    context = FakeContext()
    assert await sessions.apply_session(context, "ebay") is True
    assert context.cookies[0]["name"] == "sid"


@pytest.mark.asyncio
async def test_apply_session_without_file_is_false(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)

    class FakeContext:
        async def add_cookies(self, cookies):
            raise AssertionError("must not be called")

    assert await sessions.apply_session(FakeContext(), "missing") is False
```

Add to `tests/test_site_selection.py` or a new `tests/test_login_sites.py`:

```python
def test_login_base_url_falls_back_to_the_registry():
    from scripts.login import site_base_url

    assert site_base_url("nkon_nl") == "https://www.nkon.nl"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_sessions.py -q
```

Expected: FAIL with `ModuleNotFoundError` / missing `site_base_url`.

- [ ] **Step 3: Implement `sessions.py`**

```python
"""Saved per-site cookie sessions for sites that need a real browser login."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_DIR = Path("data/sessions")


def session_path(site_id: str) -> Path:
    return SESSION_DIR / f"{site_id}.json"


def has_session(site_id: str) -> bool:
    return session_path(site_id).is_file()


def load_cookies(site_id: str) -> list[dict]:
    path = session_path(site_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring malformed session for %s: %s", site_id, exc)
        return []
    return data if isinstance(data, list) else []


async def apply_session(context, site_id: str) -> bool:
    cookies = load_cookies(site_id)
    if not cookies:
        return False
    try:
        await context.add_cookies(cookies)
    except Exception as exc:  # noqa: BLE001 - a bad cookie must not stop a run
        logger.warning("Could not apply session for %s: %s", site_id, exc)
        return False
    return True
```

- [ ] **Step 4: Apply sessions in the search loop**

In `src/searcher/playwright_searcher.py`, import `apply_session`. In
`_execute_round`, after `page = await self.browser_manager.get_page(...)` and
before the adapter/profile search:

```python
await apply_session(page.context, site.name)
```

Do not fail the run when it returns `False`.

- [ ] **Step 5: Extend `scripts/login.py`**

Add login URLs:

```python
LOGIN_URLS = {
    "facebook": "https://www.facebook.com/login",
    "ebay": "https://www.ebay.de/",
    "amazon_de": "https://www.amazon.de/",
    "nkon_nl": "https://www.nkon.nl/en/",
    "ecoprodukt_sk": "https://ecoprodukt.sk/",
    "nay": "https://www.nay.sk/",
    "solaro_sk": "https://solaro.sk/",
    "alza": "https://www.alza.sk/",
    "bazos": "https://www.bazos.sk/",
    "backmarket": "https://www.backmarket.sk/",
}
```

Add a helper that resolves profile-only sites:

```python
def site_base_url(site: str) -> str:
    try:
        return get_adapter(site)().base_url
    except ValueError:
        from src.searcher.site_registry import by_id

        spec = by_id(site)
        if spec is None:
            raise
        return spec.base_url
```

Use `site_base_url` in `login()` and `check()` instead of `adapter.base_url`.
Use `url = LOGIN_URLS.get(site, site_base_url(site))` in `login()`.

Update the `login_sites()` CLI command in `src/cli/app.py` to use
`sessions.has_session` instead of the inline `session_dir` path, and to show
profile-only ids without the "unknown adapter" warning.

Add `ebay`, `amazon_de` and `solaro_sk` to `browser.login_sites` in
`config.yaml` and `config.example.yaml`, so `--list` shows them and
`login.py --site solaro_sk` can resolve the registry base URL.

- [ ] **Step 6: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_sessions.py tests/test_browser_registry.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/searcher/sessions.py src/searcher/playwright_searcher.py scripts/login.py src/cli/app.py tests/test_sessions.py
git commit -m "feat(sessions): load saved site cookies before searching"
```

---

### Task 3: Unlimited selector semantics

**Files:**
- Modify: `src/searcher/site_selection.py`
- Modify: `tests/test_site_selection.py`

**Interfaces:**
- Produces: `SiteSelector.select(candidates, prompt="", user_country="SK", max_sites: int | None = None) -> tuple[list[SiteCandidate], str]`
- `max_sites` is a cap only when `> 0`; `0` and `None` are unlimited.
- Prompt includes candidate `notes` and `specialties`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_site_selection.py`:

```python
@pytest.mark.asyncio
async def test_select_without_cap_returns_every_candidate():
    candidates = [_candidate(f"s{i}", "SK") for i in range(12)]
    selected, _ = await SiteSelector().select(candidates, "battery", "SK", max_sites=0)
    assert len(selected) == 12


@pytest.mark.asyncio
async def test_llm_may_select_every_candidate():
    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            return {"selected": ["a", "b", "c"], "reasoning": "all match"}

    candidates = [_candidate("a", "SK"), _candidate("b", "SK"), _candidate("c", "SK")]
    selected, _ = await SiteSelector(FakeLLM()).select(candidates, "battery", "SK")
    assert [c.id for c in selected] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_valid_empty_selection_means_no_shops():
    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            return {"selected": [], "reasoning": "no suitable shop"}

    candidates = [_candidate("a", "SK")]
    selected, reasoning = await SiteSelector(FakeLLM()).select(candidates, "battery", "SK")
    assert selected == []
    assert reasoning == "no suitable shop"


@pytest.mark.asyncio
async def test_malformed_selection_falls_back_to_all():
    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            return {"selected": "not-a-list", "reasoning": ""}

    candidates = [_candidate("a", "SK"), _candidate("b", "CZ")]
    selected, reasoning = await SiteSelector(FakeLLM()).select(candidates, "battery", "SK")
    assert [c.id for c in selected] == ["a", "b"]
    assert "Ranked by market distance" in reasoning


@pytest.mark.asyncio
async def test_prompt_includes_specialties_and_notes():
    captured = {}

    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            captured["system"] = system
            captured["user"] = user
            return {"selected": ["a"], "reasoning": "ok"}

    candidate = SiteCandidate(
        id="a", name="A", country="SK", currency="EUR",
        categories=("electronics",), conditions=("new",),
        notes="battery specialist", specialties=("battery", "18650"),
    )
    await SiteSelector(FakeLLM()).select([candidate], "18650", "SK")
    assert "battery specialist" in captured["user"]
    assert "18650" in captured["user"]
    assert "at most 6" not in captured["system"].lower()
```

Replace the old `test_llm_garbage_falls_back_to_ranking` body with the
malformed-list case above.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_site_selection.py -q
```

Expected: FAIL on the new assertions.

- [ ] **Step 3: Implement the selector changes**

`SiteSelector.select`:

```python
async def select(
    self,
    candidates: list[SiteCandidate],
    prompt: str = "",
    user_country: str = "SK",
    max_sites: int | None = None,
) -> tuple[list[SiteCandidate], str]:
    ranked = rank_by_location(candidates, user_country)
    if not ranked:
        return [], "No candidate sites match the request."
    if len(ranked) == 1:
        return ranked, "Only one site carries this category."

    picked, reasoning = await self._llm_pick(ranked, prompt, user_country)
    if picked is None:
        picked = ranked
        reasoning = "Ranked by market distance (no usable LLM selection)."
    if max_sites and max_sites > 0:
        picked = picked[:max_sites]
    return picked, reasoning
```

`_llm_pick` must return `tuple[list[SiteCandidate] | None, str]`:

* return `None, ""` on a missing LLM, timeout, malformed JSON, or a missing
  `selected` list;
* return `[], reasoning` when `selected` is a valid empty list;
* keep the candidate whitelist and dedupe behaviour.

Update the catalogue line in the prompt:

```python
f"- {c.id}: {c.name} ({c.country}, {c.currency}, "
f"categories: {', '.join(c.categories)}; "
f"specialties: {', '.join(c.specialties) or 'general'}; "
f"notes: {c.notes or 'none'})"
```

Replace "Pick at most 6" with:

```
"Select EVERY shop that is genuinely useful for this request. "
"The count is not limited; do not stop at six. "
"An empty list is valid only when no shop fits."
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_site_selection.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/searcher/site_selection.py tests/test_site_selection.py
git commit -m "feat(selection): allow the LLM to select every suitable site"
```

---

### Task 4: Runnable set, requested sites and cache key

**Files:**
- Modify: `src/searcher/playwright_searcher.py`
- Modify: `tests/test_playwright_site_selection.py`

**Interfaces:**
- Produces: `_filter_sites(user_condition, user_category, requested: set[str] | None = None) -> list[WebsiteConfig]`
- Produces: `_select_sites(..., prompt="", requested_sites: list[str] | None = None) -> list[WebsiteConfig]`
- Produces: `search(..., sites: list[str] | None = None)`
- Produces: `self._skipped_sites: list[dict]` with `{"name": str, "reason": str}`
- Cache key: `(condition, category, prompt, frozenset(requested))`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_playwright_site_selection.py`:

```python
def _real_site(name, *, enabled=True):
    from src.searcher.site_registry import by_id

    spec = by_id(name)
    return WebsiteConfig(
        name=name,
        base_url=spec.base_url,
        enabled=enabled,
        adapter_class=spec.adapter_class,
        categories=[Category(c) for c in spec.categories],
        conditions=[Condition(c) for c in spec.conditions],
        country=spec.country,
        currency=spec.currency,
    )


@pytest.mark.asyncio
async def test_zero_max_sites_selects_every_candidate():
    config = AppConfig(search=SearchConfig(
        websites=[_site(f"shop{i}", "SK") for i in range(6)],
        user_country="SK",
        max_sites=0,
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, *[f"shop{i}" for i in range(6)])

    selected = await searcher._select_sites("used", "auto", "auto")
    assert len(selected) == 6


@pytest.mark.asyncio
async def test_requested_sites_bypass_the_llm():
    class ExplodingLLM:
        async def chat_json(self, *args, **kwargs):
            raise AssertionError("the LLM must not be called")

    config = AppConfig(search=SearchConfig(
        websites=[_site("shop_a", "SK"), _site("shop_b", "SK")],
        user_country="SK",
        max_sites=0,
    ))
    config.search.diamond_search.enabled = False
    searcher = PlaywrightSearcher(config, llm=ExplodingLLM(), storage=object(), browser_manager=object())
    _profiles(searcher, "shop_a", "shop_b")

    selected = await searcher._select_sites("used", "auto", "auto", requested_sites=["shop_b"])
    assert [s.name for s in selected] == ["shop_b"]


@pytest.mark.asyncio
async def test_unknown_requested_site_raises():
    config = AppConfig(search=SearchConfig(websites=[], user_country="SK"))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)

    with pytest.raises(ValueError, match="Unknown site"):
        await searcher._select_sites("used", "auto", "auto", requested_sites=["nope"])


@pytest.mark.asyncio
async def test_blocked_site_is_skipped_with_a_reason():
    config = AppConfig(search=SearchConfig(
        websites=[_real_site("solaro_sk")],
        user_country="SK",
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)

    selected = await searcher._select_sites("new", "electronics", "solar")
    assert selected == []
    assert any(item["name"] == "solaro_sk" and "blocked" in item["reason"]
               for item in searcher._skipped_sites)


@pytest.mark.asyncio
async def test_requested_blocked_site_is_still_skipped():
    config = AppConfig(search=SearchConfig(
        websites=[_real_site("solaro_sk")],
        user_country="SK",
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)

    selected = await searcher._select_sites(
        "new", "electronics", "solar", requested_sites=["solaro_sk"]
    )
    assert selected == []
    assert any(item["name"] == "solaro_sk" and "blocked" in item["reason"]
               for item in searcher._skipped_sites)


@pytest.mark.asyncio
async def test_planned_site_is_skipped_even_with_a_profile(monkeypatch):
    from types import SimpleNamespace

    import src.searcher.playwright_searcher as module

    monkeypatch.setattr(
        module, "by_id",
        lambda name: SimpleNamespace(status="planned", notes="", specialties=())
        if name == "shop_planned" else None,
    )
    config = AppConfig(search=SearchConfig(
        websites=[_site("shop_planned", "SK")],
        user_country="SK",
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, "shop_planned")

    assert await searcher._select_sites("used", "auto", "auto") == []
    assert any(item["name"] == "shop_planned" and "profile" in item["reason"]
               for item in searcher._skipped_sites)


@pytest.mark.asyncio
async def test_needs_login_without_session_is_skipped(monkeypatch):
    from src.searcher import sessions

    monkeypatch.setattr(sessions, "has_session", lambda name: False)
    config = AppConfig(search=SearchConfig(
        websites=[_real_site("ebay")],
        user_country="SK",
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)

    assert await searcher._select_sites("used", "electronics", "phone") == []
    assert any(item["name"] == "ebay" and "login" in item["reason"].lower()
               for item in searcher._skipped_sites)


@pytest.mark.asyncio
async def test_cache_key_includes_the_prompt():
    config = AppConfig(search=SearchConfig(
        websites=[_site("shop_a", "SK")],
        user_country="SK",
        max_sites=0,
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, "shop_a")

    await searcher._select_sites("used", "auto", "battery")
    await searcher._select_sites("used", "auto", "laptop")
    assert ("used", "auto", "battery", frozenset()) in searcher._site_selection_cache
    assert ("used", "auto", "laptop", frozenset()) in searcher._site_selection_cache
```

Update the existing `test_selection_is_cached_per_condition_and_category` to
the new key shape.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_playwright_site_selection.py -q
```

Expected: FAIL on the new behaviour.

- [ ] **Step 3: Implement the runnable set and requested sites**

In `PlaywrightSearcher.__init__`:

```python
from src.searcher import sessions

self._skipped_sites: list[dict] = []
self._last_selected_sites: list[WebsiteConfig] = []
```

Add helpers:

```python
def _site_status(self, site: WebsiteConfig) -> str:
    spec = by_id(site.name)
    return spec.status if spec is not None else "working"

def _skip_reason(self, site: WebsiteConfig) -> str | None:
    status = self._site_status(site)
    if status == "blocked":
        return "blocked by the site (anti-bot or geo-block)"
    if status == "planned":
        return "no validated profile or adapter yet"
    if status == "needs_login" and not sessions.has_session(site.name):
        return "needs a saved login session"
    return None
```

`_filter_sites` gains `requested: set[str] | None = None`. It skips a site when
`_skip_reason(site)` is not None, unless the site is in `requested` and the
reason is the login session (an explicit request may still try). It appends
`{"name": site.name, "reason": reason}` to `self._skipped_sites`.

`_select_sites`:

```python
requested = self._resolve_requested_sites(requested_sites)
cache_key = (user_condition, user_category, prompt, frozenset(requested))
...
base = self._filter_sites(user_condition, user_category, requested=requested)
...
if requested:
    picked = [
        SiteCandidate(
            id=site.name, name=site.name, country=country, currency=currency,
            categories=..., conditions=..., adapter_class=site.adapter_class,
            notes=spec.notes if spec else "", specialties=spec.specialties if spec else (),
        )
        for site in base
    ]
    reasoning = "Requested by the user: " + ", ".join(sorted(requested))
else:
    picked, reasoning = await self._site_selector.select(
        candidates, prompt=prompt, user_country=user_country, max_sites=0
    )
```

`_resolve_requested_sites` matches case-insensitively against `SiteSpec.id`,
`SiteSpec.name`, and `WebsiteConfig.name`; unknown names raise:
`ValueError(f"Unknown site(s): {', '.join(unknown)}. Known ids: ...")`.

`max_sites = getattr(self.config.search, "max_sites", 0) or 0`; pass `0` when
unlimited. Reset `self._skipped_sites` at the start of `search`, and store
`self._last_selected_sites = selected` in `_select_sites`.

`_execute_round` gains `selection_prompt: str = ""`; `search` passes the
original `prompt` to every round. Add `sites: list[str] | None = None` to
`search` and pass it to `_execute_round`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_playwright_site_selection.py tests/test_site_selection.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/searcher/playwright_searcher.py tests/test_playwright_site_selection.py
git commit -m "feat(selection): respect site status, user site lists and unlimited count"
```

---

### Task 5: CLI `--sites` and no count prompt

**Files:**
- Modify: `src/cli/app.py`
- Modify: `tests/test_ask.py`
- Modify: `tests/test_cli_flags.py`

**Interfaces:**
- Produces: `_split_sites(raw: str | None) -> list[str] | None`
- Produces CLI option `--sites` on `run`, `ask` and `search`.
- Produces `run_search(..., sites: list[str] | None = None)`.
- `_ask_async(country, max_sites, sites, debug)` no longer prompts for a count.

- [ ] **Step 1: Write the failing tests**

In `tests/test_ask.py`, add:

```python
def test_ask_does_not_prompt_for_a_shop_count(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(app_module.app, ["ask"], input="kolo\n")
    assert result.exit_code == 0, result.output
    assert calls["max_sites"] is None
    assert "Max shops" not in result.output


def test_ask_forwards_sites(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(
        app_module.app, ["ask", "--sites", "bazos,alza"], input="kolo\n"
    )
    assert result.exit_code == 0, result.output
    assert calls["sites"] == ["bazos", "alza"]
```

Update `_stub` to accept and record `sites`:

```python
async def fake_run_search(
    prompt, *, condition="any", category=None, country=None,
    max_sites=None, sites=None, brief=None, plan=None, **kwargs,
):
    calls["sites"] = sites
    ...
```

Remove `test_ask_non_numeric_max_sites_reprompts`; the prompt no longer exists.
Change `test_ask_seeds_skip_questions` input to `"kolo\n"` (country and count
are supplied by flags).

In `tests/test_cli_flags.py`, add:

```python
def test_sites_reach_the_run_command(captured):
    result = runner.invoke(
        app, ["run", "--prompt", "notebook", "--sites", "alza,bazos"]
    )
    assert result.exit_code == 0, result.output
    assert "sites" in captured["kwargs"]
    assert captured["kwargs"]["sites"] == ["alza", "bazos"]
```

Keep the existing `captured["args"][-2:]` assertions only if `sites` is passed
as a keyword argument; otherwise update their index. The implementation must
pass `sites=` as a keyword to `run_async`/`_search_async`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_ask.py tests/test_cli_flags.py -q
```

Expected: FAIL on the new options / removed prompt.

- [ ] **Step 3: Implement the CLI wiring**

Add:

```python
def _split_sites(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return values or None
```

Add to `run`, `ask` and `search`:

```python
sites: str | None = typer.Option(
    None, "--sites",
    help="Comma-separated shop ids; overrides automatic selection",
),
```

Pass `sites=_split_sites(sites)` to the async functions. In `run_search`, add
`sites: list[str] | None = None` and pass it to `searcher.search(..., sites=sites)`.
Change `if max_sites:` to `if max_sites is not None:`.

In `_ask_async`, remove the `typer.prompt("Max shops", ...)` block. Keep
`max_sites` as an optional flag and pass it through. Add `sites` to the
signature and the `run_search` call.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_ask.py tests/test_cli_flags.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cli/app.py tests/test_ask.py tests/test_cli_flags.py
git commit -m "feat(cli): add --sites and remove the shop count prompt"
```

---

### Task 6: Amazon adapter

**Files:**
- Create: `src/searcher/adapters/amazon.py`
- Modify: `src/searcher/adapters/__init__.py`
- Modify: `src/searcher/site_registry.py` (status `working`)
- Modify: `config.yaml`, `config.example.yaml` (enable)
- Create: `tests/test_amazon_adapter.py`

**Interfaces:**
- Produces: `AmazonAdapter` in `ADAPTER_REGISTRY["amazon"]`
- `name = "amazon"`, `base_url = "https://www.amazon.de"`,
  `item_selector = '[data-component-type="s-search-result"]'`
- Produces `Deal.price_quote` via `extract_price_signals`/`build_price_quote`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_amazon_adapter.py`:

```python
import pytest

from src.searcher.adapters.amazon import AmazonAdapter


class FakeChild:
    def __init__(self, text="", href=None):
        self.text = text
        self.href = href

    async def inner_text(self):
        return self.text

    async def get_attribute(self, name):
        return self.href if name == "href" else None


class FakeCard:
    def __init__(self):
        self.mapping = {
            "h2 a span": FakeChild("Anker 18650 battery 2-pack"),
            ".a-price .a-offscreen": FakeChild("19,99 €"),
            "h2 a": FakeChild(href="/dp/B000TEST"),
        }

    async def query_selector(self, selector):
        return self.mapping.get(selector)

    async def inner_text(self):
        return "Anker 18650 battery 2-pack 19,99 € + shipping 4,99 €"


@pytest.mark.asyncio
async def test_amazon_card_becomes_a_deal_with_a_quote():
    deal = await AmazonAdapter().extract_deal(None, FakeCard())
    assert deal is not None
    assert deal.title.startswith("Anker")
    assert deal.price_eur == 19.99
    assert deal.url == "https://www.amazon.de/dp/B000TEST"
    assert deal.price_quote is not None
    assert deal.price_quote.shipping.cost_eur == 4.99


@pytest.mark.asyncio
async def test_amazon_captcha_is_a_block():
    class FakePage:
        url = "https://www.amazon.de/errors/validateCaptcha"
        async def title(self):
            return "Robot Check"

    reason = await AmazonAdapter().detect_block(FakePage())
    assert reason == "amazon captcha"
```

The adapter's `detect_block` returns `"amazon captcha"` for the captcha URL or
title; `search` raises `SiteBlockedError` when it sees that reason.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_amazon_adapter.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the adapter**

Create `AmazonAdapter(BaseAdapter)`:

* `default_search_url(query)` -> `f"{self.base_url}/s?k={quote_plus(query)}"`.
* `search` uses `_goto_search`, `detect_block`, waits for the card selector.
* `extract_deal`:
  * title from `h2 a span` or `h2 span`;
  * price from `.a-price .a-offscreen`, fallback whole/fraction;
  * link from `h2 a` or `a.a-link-normal`, prefix `https://www.amazon.de`;
  * condition from title/card text (`used`, `renewed`, `neu`);
  * `metadata["card_text"]`, `metadata["source"] = "amazon"`;
  * attach `build_price_quote` from `extract_price_signals`.
* `detect_block` adds captcha markers on top of `super().detect_block(page)`.
* Register in `ADAPTER_REGISTRY` and `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_amazon_adapter.py tests/test_adapters.py -q
```

Expected: PASS.

- [ ] **Step 5: Enable Amazon and commit**

Set `amazon_de` status to `working` in `site_registry.py`, enable it in
`config.yaml` and `config.example.yaml`, and update `test_summary_counts` to
`working == 3`, `planned == 24`.

```bash
git add src/searcher/adapters/amazon.py src/searcher/adapters/__init__.py src/searcher/site_registry.py config.yaml config.example.yaml tests/test_amazon_adapter.py tests/test_site_registry.py
git commit -m "feat(amazon): add Amazon.de adapter"
```

---

### Task 7: eBay price quote and block markers

**Files:**
- Modify: `src/searcher/adapters/ebay.py`
- Modify: `src/searcher/adapters/base.py`
- Modify: `config.yaml` (enable eBay; keep `config.example.yaml` disabled)
- Modify: `tests/test_adapters.py`

**Interfaces:**
- eBay `Deal` carries `price_quote` and `metadata["card_text"]`.
- `BLOCK_MARKERS` recognises the eBay error page.
- eBay stays `needs_login` from Task 1; config.yaml enables it for users with a session.

- [ ] **Step 1: Write the failing tests**

In `tests/test_adapters.py`:

```python
@pytest.mark.asyncio
async def test_ebay_card_attaches_a_price_quote():
    class FakeChild:
        def __init__(self, text="", href=None):
            self.text = text
            self.href = href
        async def inner_text(self):
            return self.text
        async def get_attribute(self, name):
            return self.href if name == "href" else None

    class FakeCard:
        mapping = {
            ".s-card__title": FakeChild("18650 battery"),
            ".s-card__price": FakeChild("19,99 €"),
            'a[href*="/itm/"]': FakeChild(href="https://www.ebay.de/itm/1"),
            ".s-card__subtitle": FakeChild("Used"),
        }
        async def query_selector(self, selector):
            return self.mapping.get(selector)
        async def inner_text(self):
            return "18650 battery 19,99 € Used + shipping 4,99 €"

    deal = await EbayAdapter().extract_deal(None, FakeCard())
    assert deal is not None
    assert deal.price_quote is not None
    assert deal.price_quote.shipping.cost_eur == 4.99


@pytest.mark.asyncio
async def test_ebay_error_page_is_blocked():
    reason = await EbayAdapter().detect_block(
        FakePage(url="https://www.ebay.de/sch/i.html", title="Error Page | eBay")
    )
    assert reason == "ebay bot block"
```

Update the `BLOCK_MARKERS` test expectation to `"ebay bot block"`. No summary
count changes: eBay is already `needs_login` from Task 1.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_adapters.py -q
```

Expected: FAIL on the missing quote.

- [ ] **Step 3: Implement the eBay changes**

In `extract_deal`, capture the full card text and attach the quote, following
the Alza/Bazos pattern:

```python
full_text = " ".join((await element.inner_text()).split())
signals = extract_price_signals(full_text, price_eur, original_currency)
...
metadata={"source": "ebay", ..., "card_text": full_text[:2000]}
price_quote=build_price_quote(...)
```

Keep the existing title/price/link/subtitle selectors. Add
`("error page", "ebay bot block")` to `BLOCK_MARKERS` in
`src/searcher/adapters/base.py`. Enable eBay in `config.yaml` with
`requires_login: true`; add a comment that a session is needed. Keep
`config.example.yaml` disabled so its enabled set still equals the working
sites.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_adapters.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/searcher/adapters/ebay.py src/searcher/adapters/base.py config.yaml tests/test_adapters.py
git commit -m "feat(ebay): attach price quotes and block markers"
```

---

### Task 8: nkon, ecoprodukt, Solaro and Nay profiles

**Files:**
- Create: `src/searcher/site_profiles/nkon_nl.yaml`
- Create: `src/searcher/site_profiles/ecoprodukt_sk.yaml`
- Create: `src/searcher/site_profiles/solaro_sk.yaml`
- Modify: `src/searcher/site_registry.py` (statuses)
- Modify: `config.yaml`, `config.example.yaml` (enable nkon/ecoprodukt/nay)
- Modify: `tests/test_site_profiles.py`
- Modify: `tests/test_profile_adapter.py`
- Modify: `tests/test_site_registry.py`

**Interfaces:**
- Profiles load via `load_profile("nkon_nl")` etc.
- nkon/ecoprodukt/nay status `working`; Solaro `blocked`.
- `ProfileAdapter` extracts title/price/URL/quote from each profile.

- [ ] **Step 1: Write the failing tests**

In `tests/test_site_profiles.py`:

```python
def test_new_profiles_load_with_expected_status():
    assert load_profile("nkon_nl").status == "validated"
    assert load_profile("ecoprodukt_sk").status == "validated"
    assert load_profile("solaro_sk").status in {"blocked", "needs_login"}
```

In `tests/test_profile_adapter.py`, add a nkon card test:

```python
@pytest.mark.asyncio
async def test_nkon_profile_extracts_a_battery_card():
    profile = load_profile("nkon_nl")
    element = FakeElement(
        mapping={
            ".product-item-link": FakeChild("18650 battery", href="/en/18650"),
            ".price": FakeChild("4,99 €"),
        },
        text="18650 battery 4,99 €",
    )
    deal = await ProfileAdapter(profile=profile).extract_deal(None, element)
    assert deal is not None
    assert deal.title == "18650 battery"
    assert deal.price_eur == 4.99
    assert deal.price_quote is not None
```

Update `test_summary_counts` to `working == 6`, `blocked == 4`,
`needs_login == 2`, `planned == 21`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_site_profiles.py tests/test_profile_adapter.py -q
```

Expected: FAIL on missing profiles.

- [ ] **Step 3: Write the profiles**

`nkon_nl.yaml`:

```yaml
version: 1
site_id: nkon_nl
base_url: https://www.nkon.nl
status: validated
last_verified: '2026-11-03'
currency: EUR
search:
  url_template: https://www.nkon.nl/en/catalogsearch/result/?q={query}
  query_param: q
  category_urls:
    electronics: https://www.nkon.nl/en/catalogsearch/result/?q={query}
filters:
  extras: {}
extraction:
  item_selector: li.product-item
  title_selector: .product-item-link
  price_selector: .price
  link_selector: .product-item-link
  image_selector: .product-image-photo
  condition_selector: .product-item-link
notes: Magento battery specialist; verified search path 2026-11-03.
```

`ecoprodukt_sk.yaml`:

```yaml
version: 1
site_id: ecoprodukt_sk
base_url: https://ecoprodukt.sk
status: validated
last_verified: '2026-11-03'
currency: EUR
search:
  url_template: https://ecoprodukt.sk/?s={query}&post_type=product
  query_param: s
  category_urls:
    electronics: https://ecoprodukt.sk/?s={query}&post_type=product
filters:
  extras: {}
extraction:
  item_selector: ul.products li.product
  title_selector: .woocommerce-loop-product__title
  price_selector: .price
  link_selector: a.woocommerce-LoopProduct-link
  image_selector: img
  condition_selector: .product__badge, .onsale
notes: WooCommerce photovoltaics and batteries; verified 2026-11-03.
```

`solaro_sk.yaml`: the same WooCommerce shape with
`status: blocked`, `url_template: https://solaro.sk/?s={query}&post_type=product`
and notes "Cloudflare challenge; keep disabled until a session passes."

- [ ] **Step 4: Enable the working sites**

Set nkon/ecoprodukt/nay status `working`; keep Solaro `blocked` and disabled.
Enable nkon, ecoprodukt and nay in `config.yaml` and
`config.example.yaml`. Update `test_summary_counts`.

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_site_profiles.py tests/test_profile_adapter.py tests/test_site_registry.py -q
```

Expected: PASS. If a live replay is available, run
`python scripts/discover_sites.py validate --site nkon_nl` and
`--site ecoprodukt_sk`; keep the profile `draft` and the registry `planned` if
the replay fails.

- [ ] **Step 6: Commit**

```bash
git add src/searcher/site_profiles/nkon_nl.yaml src/searcher/site_profiles/ecoprodukt_sk.yaml src/searcher/site_profiles/solaro_sk.yaml src/searcher/site_registry.py config.yaml config.example.yaml tests/test_site_profiles.py tests/test_profile_adapter.py tests/test_site_registry.py
git commit -m "feat(catalog): add nkon, ecoprodukt, Solaro and Nay profiles"
```

---

### Task 9: SitePlan and "Shops searched" report section

**Files:**
- Modify: `src/searcher/site_selection.py`
- Modify: `src/searcher/playwright_searcher.py`
- Modify: `src/cli/app.py`
- Modify: `src/output/processor.py`
- Modify: `tests/test_processor_details.py`
- Modify: `tests/test_playwright_site_selection.py`

**Interfaces:**
- Produces `SitePlan` dataclass in `site_selection.py`:
  `selected: list[str]`, `reasoning: str`, `skipped: list[dict]`
- Produces `SitePlan.as_dict() -> dict`
- Produces `PlaywrightSearcher.site_plan -> SitePlan`
- Produces `ResultProcessor.save_results(..., site_plan: SitePlan | None = None)`

- [ ] **Step 1: Write the failing tests**

In `tests/test_processor_details.py`:

```python
def test_report_lists_selected_and_skipped_shops(tmp_path):
    from src.searcher.site_selection import SitePlan

    processor = ResultProcessor(load_config())
    plan = SitePlan(
        selected=["alza", "nkon_nl"],
        reasoning="battery request",
        skipped=[{"name": "solaro_sk", "reason": "blocked by the site"}],
    )
    json_path, md_path = asyncio.run(
        processor.save_results([], str(tmp_path), prompt="18650", site_plan=plan)
    )

    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    assert payload["site_plan"]["selected"] == ["alza", "nkon_nl"]
    markdown = Path(md_path).read_text(encoding="utf-8")
    assert "## Shops searched" in markdown
    assert "nkon_nl" in markdown
    assert "solaro_sk" in markdown and "blocked" in markdown
```

In `tests/test_playwright_site_selection.py`:

```python
@pytest.mark.asyncio
async def test_site_plan_contains_selected_and_skipped(monkeypatch):
    config = AppConfig(search=SearchConfig(
        websites=[_real_site("solaro_sk"), _site("shop_a", "SK")],
        user_country="SK",
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, "shop_a")

    await searcher._select_sites("new", "electronics", "solar")
    assert "shop_a" in searcher.site_plan.selected
    assert any(item["name"] == "solaro_sk" for item in searcher.site_plan.skipped)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_processor_details.py tests/test_playwright_site_selection.py -q
```

Expected: FAIL on missing `SitePlan`/`site_plan` parameter.

- [ ] **Step 3: Implement `SitePlan` and the search handoff**

In `site_selection.py`:

```python
@dataclass(frozen=True)
class SitePlan:
    selected: list[str]
    reasoning: str = ""
    skipped: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "selected": list(self.selected),
            "reasoning": self.reasoning,
            "skipped": list(self.skipped),
        }
```

`PlaywrightSearcher` keeps `self._site_selection_reason`,
`self._skipped_sites` and `self._last_selected_sites`; add:

```python
@property
def site_plan(self) -> SitePlan:
    return SitePlan(
        selected=[site.name for site in self._last_selected_sites],
        reasoning=self._site_selection_reason,
        skipped=list(self._skipped_sites),
    )
```

Store `self._last_selected_sites = selected` in `_select_sites` (Task 4 already
adds the field; this task uses it).

In `run_search`, after the search:

```python
site_plan = searcher.site_plan
...
json_path, md_path = await processor.save_results(
    deals, config.output.directory, prompt=prompt, site_plan=site_plan
)
```

- [ ] **Step 4: Add the report section**

`ResultProcessor.save_results` gains `site_plan: SitePlan | None = None`.
`_deal_to_dict` is unchanged. The JSON payload gains `"site_plan":
site_plan.as_dict() if site_plan else None`.

`_to_markdown` gains `site_plan: SitePlan | None = None` and prints the
section before the `if not relevant` early return, so an empty search still
shows which shops were tried:

```markdown
## Shops searched

Selected automatically: alza, nkon_nl.
Reason: battery request.

Skipped: solaro_sk (blocked by the site).
```

If `site_plan is None`, omit the section. If `selected` is empty, print
"No shop was selected." If `skipped` is empty, omit the "Skipped" line.

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_processor_details.py tests/test_playwright_site_selection.py tests/test_ask.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/searcher/site_selection.py src/searcher/playwright_searcher.py src/cli/app.py src/output/processor.py tests/test_processor_details.py tests/test_playwright_site_selection.py
git commit -m "feat(report): list selected and skipped shops"
```

---

### Task 10: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Optional: `docs/specs/2026-11-03-site-catalog-selection-design.md` if an
  implementation detail changed.

- [ ] **Step 1: Update the README**

Add a section after "Which shops get searched" (or next to it):

```markdown
### Automatic and explicit shop selection

By default the LLM receives every runnable shop with its specialties and notes
and selects all that fit; there is no count limit. `--sites alza,nkon_nl`
bypasses the LLM and searches exactly those shops. A blocked or unvalidated
shop is skipped with a reason in the report's "Shops searched" section.

Sites that need a real session (eBay, Solaro) use
`python scripts/login.py --site <id>`; the cookies are stored under
`data/sessions/` and loaded automatically.
```

- [ ] **Step 2: Update the CHANGELOG**

Under `[Unreleased] / Added`:

```markdown
- Unlimited site selection: the LLM now sees shop specialties and may select
  every suitable shop; `--sites` overrides automatic selection. The `ask`
  wizard no longer asks for a shop count.
- Amazon.de adapter, eBay price quotes and login status, plus nkon.nl,
  ecoprodukt.sk, Solaro.sk (blocked) and Nay.sk catalogue entries.
- Saved cookie sessions under `data/sessions/` are applied before each site
  search; blocked and planned shops are listed in the report with a reason.
```

- [ ] **Step 3: Run the full suite**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass; the previous baseline was 576 passed, 11 skipped, so
expect at least 576 passed and 11 skipped (more tests are fine).

- [ ] **Step 4: Run a deterministic smoke test**

Run:

```bash
python -m pytest tests/test_site_selection.py tests/test_playwright_site_selection.py tests/test_processor_details.py -q
```

Expected: PASS.

Optional live smoke, when a network and a browser are available:

```bash
python scripts/login.py --site ebay --check
python -m src.cli run --prompt "18650 battery" --sites nkon_nl,ecoprodukt_sk --debug
python -m src.cli run --prompt "solar inverter" --debug
```

Expected: the report contains a `## Shops searched` section; nkon/ecoprodukt
return cards or a clear skip reason; Solaro is skipped as blocked.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document site selection and new shops"
```
