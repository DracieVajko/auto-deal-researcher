# Winner-First Report — Design

Date: 2026-11-03
Status: approved in session (user asked to implement all improvement ideas)
Scope: report ordering and detail only. Runtime web-search sources are a
separate follow-up.

## 1. Problem

The current Markdown report starts with a summary table, then top picks,
price history, comparison, and only then the deal cards. The winner is buried
in the table and the user has to scroll to the details. Runner-ups are not
distinguished from the rest, and the filtered-out table is at the very end.

The user wants the winner first, with full detail, then runner-ups, then all
found deals, then filtered-out deals with reasons and links.

## 2. Goals

* G1 — The best deal (highest score) is the first section and shows the full
  deal card: price breakdown, specs, pros/cons, alternatives, score breakdown,
  checklist and link.
* G2 — The next two top picks are shown as runner-ups with full cards and a
  label (`Cheapest`, `Best price/performance`, `Runner-up`).
* G3 — A compact `All found` table lists every relevant deal with link, price,
  condition, site, score and verdict.
* G4 — Remaining deals keep their full cards under `Other deals`.
* G5 — `Shops searched` and `Filtered out` are at the end, both with links and
  reasons.
* G6 — Existing JSON/CSV fields and scoring do not change.
* G7 — The report never repeats a deal card: winner and runner-ups appear once
  at the top, remaining deals once under `Other deals`.

## 3. Non-goals

* External source discovery and comparison citations (next sub-project).
* LLM spec extraction beyond the existing `DealAnalysis.specs`.
* Changing the scoring model or the winner selection algorithm.
* PDF/HTML rendering.

## 4. Order

1. Header (`Query`, counts).
2. `## Winner` — highest-score deal, full card, label `🏆 Best overall`.
3. `## Runner-ups` — next two top picks, full cards, labels:
   `💰 Cheapest`, `⚡ Best price/performance`, `Runner-up`.
4. `## All found` — compact table of every relevant deal.
5. `## Comparison` — current side-by-side table for the winner and runner-ups,
   including specs when available.
6. `## Other deals` — full cards for remaining relevant deals.
7. `## Shops searched` — selected/skipped sites and reasons.
8. `## Filtered out` — removed deals, reason and link.

Price history charts stay between `All found` and `Comparison` when present,
because they are supporting evidence, not a deal card.

## 5. Winner and runner-up selection

* Winner = `max(relevant, key=score)`. `relevant` is already sorted by score,
  so this is stable.
* Runner-ups = the next two analyses in score order. If a top pick set exists,
  prefer its `Cheapest` / `Best price/performance` members for labels, but never
  duplicate a deal.
* Every deal appears exactly once as a full card. Deals not in the top three
  go to `Other deals`.

## 6. Labels

`_deal_card` gains an optional `label: str = ""` parameter. The label is printed
directly under the heading:

```markdown
### 1. Samsung 18650 30Q

**Pick:** 🏆 Best overall
```

The winner gets `🏆 Best overall`; runner-ups get their top-pick label or
`Runner-up`.

## 7. Compatibility

* `_to_markdown` keeps the same keyword arguments; only the body order changes.
* `save_results` JSON/CSV/XLSX payloads are unchanged.
* Tests that looked for `## Summary` are updated to `## All found`.
* `## Deal details` is renamed to `## Other deals`; tests are updated.

## 8. Testing

* Winner is the first `##` section after the header and contains the full card.
* Runner-ups contain at most two cards and no duplicate URLs.
* `All found` contains every relevant deal exactly once.
* `Other deals` contains exactly the deals not shown at the top.
* Filtered-out deals remain at the end with reason and link.
* A report with one relevant deal has a winner and no empty runner-up section.
* A report with zero relevant deals still shows `No deals matching` and the
  filtered-out section.

## 9. Risks

* The report becomes longer because the winner is detailed twice if the same
  deal is kept in `All found`. It is a table row, not a second card, so the
  duplication is acceptable and deliberate.
* Existing consumers may grep for `## Summary` or `## Deal details`. The README
  and tests are updated; this is a deliberate report contract change.
