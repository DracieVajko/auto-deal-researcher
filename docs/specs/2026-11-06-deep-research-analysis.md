# Deep Research Analysis & Next-Implementation Plan

**Date:** 2026-11-06  
**Source:** `autodeal searcher deepresearch.txt` + `autodeal searcher dokuemntacia.txt`  
**Repo state:** `master @ 63ac0f4` (all 5 deep-research sub-projects from prior sessions are complete)

## Executive Summary

All five research areas from `deepresearch.txt` have been addressed across prior implementation sessions:

| Area | Status | What was built |
|------|--------|----------------|
| 1. Search quality & relevance | ✅ Done | Multi-language NLP filter extraction (SK/CZ/DE/PL/EN), anti-bot stealth context + challenge detection + retry, pagination (multi-page up to `pages_per_site`), generic product-card extraction |
| 2. LLM integration | ✅ Done | File-based LLM response cache, spec-based deal scoring (price/power/weight/battery/condition/warranty/trust), comparison engine (winner/runner-ups/table), `find-replacement` CLI + interactive wizard |
| 3. Price tracking & analytics | ✅ Done | Effective-price (price+shipping) tracking, price-drop/new-low/fake-promo detection, alert rules (Alert objects), CLI logging + report surface |
| 4. User experience & automation | ✅ Done | Interactive CLI wizard (`--interactive`), scheduling hook (`monitor`), notification channels (console/email/system/webhook/discord) |
| 5. Architecture & performance | ✅ Done | File-based search response cache (TTL, stats, clear), `cache` CLI (`--stats`/`--clear`), `cache_ttl_seconds` config |

**Remaining work** maps to the documentation roadmap (`dokumentacia.txt` §13) and the unanswered research questions. The highest-impact, lowest-effort next item is **user-configurable price-alert thresholds with notification delivery** — it completes research goal 3 (price drop alerts with statistical significance) using already-built infrastructure (price tracker + notification channels).

---

# Deep Research Report (per deepresearch.txt output format)

## Area 1 — Search quality & relevance

### Key findings
1. **Multi-language NLP filter extraction:** Central European marketplaces (SK/CZ/DE/PL/EN) use distinct keywords for condition ("nové"/"gebraucht"/"nowe"/"new"), price ("do"/"max"/"unter"/"under"), and category ("auto"/"elektronika"/"auto"/"car"). Deterministic keyword maps with whole-word matching (`\b`) and a SK-first tie-break outperform a single LLM call for price/condition because they are deterministic, offline-capable, and free. Source: existing `filter_extractor.py` keyword maps; marketplace listing conventions observed on bazos.sk, alza.sk, mobile.de, idealo.de.
2. **Anti-bot protection:** mobile.de, idealo.de, alza.sk deploy Cloudflare challenges, CAPTCHAs, and rate limiting. Best practice without heavy deps: rotate user-agent + realistic viewport + remove `navigator.webdriver` fingerprint + set `Accept-Language` headers + retry-with-exponential-backoff on detected block + fail fast (skip site, log reason, continue). Source: Playwright stealth patterns; Cloudflare challenge markers (`just a moment`, `checking your browser`, `are you a robot`).
3. **Pagination:** Marketplace result pages expose `rel="next"` anchors or language-variant "Next" text ("Ďalšia"/"Další"/"Nächste"/"Dalej"/"Next"). Deterministic selector priority list + click-or-navigate fallback handles both static and JS-driven pagination without a heavy scraping library. Source: existing `pagination.py`.
4. **Structured product-data extraction:** No single open-source library dominates arbitrary e-commerce extraction without heavy ML deps. CSS selectors per site + regex price/date parsing is the pragmatic, dependency-free approach (Playwright already a dependency). Source: existing `extract.py`.

### Actionable recommendations
- Keep deterministic keyword maps as the primary filter extractor; LLM only as a refinement/fallback (offline-safe, zero cost).
- Rotate user-agents per site and add `sec-ch-ua`/`sec-ch-platform` client-hints to stealth context for anti-bot resilience on mobile.de/idealo.de/alza.sk.
- Cap pagination at `pages_per_site` (default 3) to bound anti-bot exposure while capturing most relevant results.
- Add per-site selector overrides in `site_profiles` for sites whose markup deviates from defaults.

### Trade-offs
- Deterministic NLP vs. LLM: deterministic is free/offline but misses novel phrasings; LLM is flexible but costs tokens/latency and needs network. Recommendation: deterministic first, LLM optional enhancement (already the design).
- Stealth headers vs. detection risk: more headers reduce block rate but increase fingerprint surface. Keep the set minimal and rotate only UA + viewport.

### Priority: HIGH (already implemented; maintain + extend stealth headers)

---

## Area 2 — LLM integration

### Key findings
1. **Best open-source LLMs (7–30B) for structured JSON extraction:** Qwen2.5-7B/14B, Llama-3.1-8B, and Gemma-2-9B consistently produce valid JSON for structured extraction when prompted with a strict schema and `max_tokens` budget. For multi-language (SK/CZ/DE/PL/EN), Qwen2.5 and Llama-3.1 have the strongest multilingual coverage. Source: community LLM benchmarks (Hugging Face Open LLM Leaderboard); local LM Studio/Ollama already supported by ADS.
2. **Reducing LLM latency:** (a) response caching keyed by provider+model+prompt SHA-256 eliminates repeated extractions; (b) smaller models (7B) for filter extraction, larger only for deal scoring; (c) prompt optimization — single combined extract_search_filters call (category + filters in one request) already implemented; (c) local-model auto-load/unload via `lms` CLI already handled. Source: existing `llm_cache.py`, `llm/client.py`.
3. **Deal scoring / winner selection:** Weighted multi-criteria scoring (price/power/weight/battery/condition/warranty/trust) with redistribution when criteria are missing is more robust than "cheapest only". Source: existing `deal_scorer.py`, `comparison_engine.py`.
4. **Hallucination handling:** Validate LLM-extracted evidence as exact substrings of card text; drop responses with invented evidence or impossible numbers; never trust model-provided trust — recompute deterministically. Source: existing `price_llm.py` validation, `pricing.py` trust model.

### Actionable recommendations
- Keep the provider fallback chain (local LM Studio/Ollama → cloud mistral/gemini/openrouter → deterministic fallback).
- Route filter extraction to the smallest capable model (7B) and deal scoring to a larger model only when available; fall back to deterministic scoring when LLM is unavailable.
- Cache LLM responses with 24h TTL; invalidate on config/model change.
- Keep validation: every evidence entry must be an exact substring of the listing text.

### Trade-offs
- Local vs. cloud: local is free/private but slower and model-quality varies; cloud is faster/better but needs API keys and network. Recommendation: fallback chain as implemented.
- Caching vs. freshness: 24h TTL is appropriate for specs (slow-changing) but too long for live prices; prices must never be cached from LLM — always scrape live.

### Priority: HIGH (implemented; maintain)

---

## Area 3 — Price tracking & analytics

### Key findings
1. **Price history tracking:** Track effective price (price + shipping) — raw price alone misranks when shipping varies. Store full quote JSON in metadata for audit. Source: existing `pricing.py`, `schema.py` SCHEMA_VERSION 5 (`effective_price_eur`, `price_kind` on deals + price_history).
2. **Price-drop alerts with statistical significance:** Trigger on effective-price change >= threshold% (default 5%) between earliest and latest sighting in a window, not on any single change. Compare latest vs. earliest to avoid noise from intermediate volatility. Source: existing `detect_price_drops`.
3. **Fake-discount detection:** A "fake promo" occurs when the listing's regular ("was") price is significantly higher than historical effective prices (default 30% threshold). Compare regular_price_eur vs. max historical effective price. Source: existing `detect_fake_promos`.
4. **Price trend charts without heavy deps:** SVG charts generated in pure Python (stdlib) — no matplotlib/plotly needed. Already implemented for price history. Source: existing SVG chart generation.

### Actionable recommendations
- Add user-configurable price-alert thresholds: user sets a target price per item/URL; alert when effective price <= target. Notifications delivered via existing channels (console/email/system/webhook/discord).
- Keep new-low detection (lowest effective price in N days) and fake-promo detection as complementary alerts.
- Backfill `effective_price_eur = price_eur`, `price_kind = unknown` for old rows (already done in migration).

### Trade-offs
- Threshold% vs. absolute EUR: % is relative to item value; absolute is predictable. Recommendation: support both (threshold% default 5%, optional absolute target).
- Alert cooldown: prevent spam on oscillating prices; cooldown per URL (default 60 min) already exists in `NotificationManager`.

### Priority: **HIGH — SELECTED FOR NEXT IMPLEMENTATION**

---

## Area 4 — User experience & automation

### Key findings
1. **CLI wizard:** Interactive `input()`-based wizard (item → category → condition → price range → confirm) works on all platforms with zero new deps. Source: existing `wizard.py`, `find-replacement --interactive`.
2. **Scheduling:** `monitor` command runs prompt-file searches on an interval (hours), records runs, sends notifications. Source: existing `monitor`, `scheduler.tasks`.
3. **Web dashboard:** A pure-Python HTTP server (`http.server`) could serve JSON/Markdown results without Flask/Django. Not yet implemented. Source: dokumentacia roadmap.
4. **Notification strategies:** Email digest (SMTP), system toast, webhook, Discord, console. All already implemented. Source: `src/notifications/`.

### Actionable recommendations
- Price-alert thresholds feed into notification channels (email digest most useful for daily/weekly summary).
- Consider a minimal web dashboard (`http.server`) serving latest results JSON — low dep, high visibility.
- Saved searches as YAML profiles (user profiles) — low effort, high reuse.

### Trade-offs
- Web dashboard vs. CLI/report files: dashboard adds a long-running server process; report files are already AI-named and timestamped. Recommendation: dashboard as a later, optional item.
- Email digest vs. instant push: digest reduces spam for monitoring runs; instant for price drops. Recommendation: support both via existing channel cooldowns.

### Priority: MEDIUM (dashboard optional; alert thresholds covered under Area 3)

---

## Area 5 — Architecture & performance

### Key findings
1. **Parallel marketplace searches:** `asyncio` + semaphore (default concurrency=3) searches sites in parallel without blocking. Higher concurrency = faster but more rate-limit/anti-bot risk. Source: existing `playwright_searcher.py` `run_site` semaphore.
2. **Caching scraped pages:** File-based search-response cache keyed by (site, query, filters_hash) with TTL avoids redundant requests. Source: existing `search_cache.py`, `cache_ttl_seconds` config.
3. **Plugin system for adapters:** `ADAPTER_REGISTRY` keyed by adapter class name; new adapters register without code changes to core. Source: existing `adapters/base.py`, registry.
4. **Scraping pitfalls:** anti-bot blocks, cookie sessions, currency conversion, pagination, decoy listings (eBay). Mitigations already in place per-site.

### Actionable recommendations
- Per-site concurrency limits based on health score (sites with blocks get lower concurrency) — uses existing `SelectorHealthTracker`.
- Cache scraped listing HTML (not just results) for re-parsing when selectors change — optional, storage trade-off.
- Add more site profiles/aliases for new marketplaces.

### Trade-offs
- Concurrency vs. anti-bot: higher concurrency speeds search but triggers blocks. Recommendation: health-based adaptive concurrency.
- Cache HTML vs. results only: HTML cache enables re-parsing but costs disk; results cache is sufficient for most. Recommendation: results cache only (implemented).

### Priority: MEDIUM (health-based concurrency optional)

---

## Selected Next Implementation: Price Alert Thresholds with Notification Delivery

**Rationale:** Completes research goal 3 (price drop alerts with statistical significance + user-defined thresholds). Uses already-built infrastructure (price tracker `check_price_drops`, `check_fake_promos`, `check_new_lows` + `NotificationManager` channels + `StorageManager`). High user value: users get notified when a watched item drops below their target price. Listed in `dokumentacia.txt` §13 ("Price alert thresholds — notifikácia pri poklese pod X€").

**Scope (single sub-project):**
- `PriceAlertRule` model: URL + target_price_eur + condition + channels + cooldown.
- `AlertRuleEngine`: evaluates all active rules against latest effective prices; produces `Alert` objects.
- `StorageManager`: persist/load rules (SQLite `alert_rules` table).
- CLI: `ads alert-rule add/list/remove` commands.
- Integration: after each `run`/`monitor`, evaluate rules and send alerts via notification channels.
- Tests: rule CRUD, threshold trigger (effective price <= target), no false trigger above threshold, cooldown behavior, notification channel selection.

**Estimated effort:** 1–2 sessions. **Dependencies:** none new (stdlib + existing sqlite-utils/playwright/pytest).

---

## Implementation plan

Per the project workflow (AGENTS.md):
1. ✅ Deep research analysis — **this document** (spec at `docs/specs/2026-11-06-deep-research-analysis.md`)
2. Design spec for price-alert thresholds → `docs/specs/2026-11-06-price-alert-thresholds-design.md`
3. User approval (skipped per "run until finished" instruction — proceeding with implementation)
4. `writing-plans` → implementation plan
5. TDD implementation per plan, full suite after each task
6. Commit and push

I am proceeding directly to implementation per the user's instruction to run until finished without pausing for approval.
