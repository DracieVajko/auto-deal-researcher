# Design: LLM Integration — Caching, Deal Scoring & Comparison (Sub-project 3)

**Date:** 2026-11-05  
**Deep research goal:** LLM integration (caching, hallucination handling, deal scoring)  
**Status:** Draft  

## Problem

The replacement finder needs to:
1. Compare candidate items against the reference item's specs (power, battery, weight, price, etc.)
2. Score deals based on how well they match the user's requirements
3. Avoid re-paying for the same LLM extraction (caching)
4. Validate LLM outputs against evidence (hallucination handling)

Currently there's an LLMClient with fallback chain and circuit breaker, but no:
- Response caching (repeated extractions of the same card text are re-paid)
- Spec-based deal scoring (how well does a candidate match the reference?)
- Comparison logic (side-by-side spec comparison)

## Scope

**In scope:**

1. **LLM response cache** — file-based cache keyed by (provider, model, prompt_hash). Stores raw responses. TTL configurable (default 24h). Avoids re-paying for identical extractions.
2. **Deal scorer** — `DealScorer` class that scores a candidate deal against reference ItemSpecs:
   - Price match (within % of reference price)
   - Power match (kW/hp within %)
   - Weight match (kg within %)
   - Battery/range match (for EVs)
   - Condition preference (new > refurbished > used)
   - Warranty bonus (retailer warranty)
   - Trust bonus (from PriceQuote trust)
   - Output: score 0-100 + breakdown
3. **Comparison engine** — `ComparisonEngine` that takes a reference ItemSpecs + list of candidate deals, scores each, ranks them, and produces a comparison table with winner/recommendation.
4. **Review integration** — attach review summary (from Sub-project 1) to each candidate in the comparison.
5. **CLI command** — `ads find-replacement --item "Citroen eC3"` that chains: research specs → extract filters → search → score → compare → report.

**Out of scope (later sub-projects):**
- Interactive CLI wizard (Sub-project 4)
- Parallel search architecture (Sub-project 5)

## Architecture

```
src/intelligence/llm_cache.py          (new) — File-based LLM response cache
  ├── LLMCache.get(key) -> str | None
  ├── LLMCache.set(key, response) -> None
  └── cache_key(provider, model, prompt) -> str

src/intelligence/deal_scorer.py        (new) — Spec-based deal scoring
  ├── DealScorer.score(deal, reference_specs) -> DealScore
  └── DealScore (dataclass: score, breakdown, reasons)

src/intelligence/comparison_engine.py  (new) — Multi-candidate comparison
  ├── ComparisonEngine.compare(reference, candidates) -> ComparisonResult
  └── ComparisonResult (dataclass: winner, runner_ups, ranked, table)

src/cli/app.py                         (modify) — find-replacement command
```

## Data model

```python
@dataclass
class DealScore:
    deal_url: str
    score: float              # 0-100
    breakdown: dict[str, float]  # per-criterion scores
    reasons: list[str]        # human-readable why/why-not
    matches_requirements: bool

@dataclass
class ComparisonResult:
    reference: ItemSpecs
    candidates: list[tuple[Deal, DealScore]]
    winner: Deal | None
    runner_ups: list[Deal]
    comparison_table: list[dict]
```

## Scoring criteria (weights)

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Price match | 30% | Within 10% of reference = full score |
| Power match | 20% | Within 20% of reference kW = full score |
| Weight match | 10% | Within 20% of reference kg = full score |
| Battery/range | 15% | For EVs: within 20% of reference |
| Condition | 15% | New=100, Refurbished=70, Used=40 |
| Warranty | 5% | Retailer warranty = bonus |
| Trust | 5% | From PriceQuote trust score |

## Error handling

- Cache miss: call LLM, store result
- Cache hit: return stored result, no LLM call
- LLM failure: fall back to deterministic scoring (price only)
- Missing specs fields: skip that criterion, redistribute weight
- No candidates: return empty comparison with "no matches found"

## Testing

- Unit tests for LLMCache (get/set/expire)
- Unit tests for DealScorer (known specs → expected score)
- Unit tests for ComparisonEngine (ranking, winner selection)
- Integration test: find-replacement flow end-to-end with mocked search
- Full suite must remain green (698 passed, 11 skipped baseline)

## Files to create/modify

**Create:**
- `src/intelligence/llm_cache.py`
- `src/intelligence/deal_scorer.py`
- `src/intelligence/comparison_engine.py`
- `tests/test_llm_cache.py`
- `tests/test_deal_scorer.py`
- `tests/test_comparison_engine.py`
- `docs/specs/2026-11-05-llm-integration-design.md` — this file

**Modify:**
- `src/cli/app.py` — add `find-replacement` command
- `src/llm/client.py` — integrate LLMCache into chat_json path

## Design decisions

- **File-based cache**: simple, no new dependencies, persists across runs
- **Cache key**: SHA256 of (provider + model + prompt) — deterministic
- **Score 0-100**: consistent with existing score format in ResultProcessor
- **Weight redistribution**: if a criterion is missing (e.g., no battery_kwh for non-EV), its weight is redistributed proportionally
