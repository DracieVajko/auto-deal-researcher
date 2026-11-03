# Winner-First Report Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Put the winner and full detail first, then runner-ups, all found deals, comparison, other cards, shops searched and filtered-out deals.

**Architecture:** Reorder `ResultProcessor._to_markdown`, add a `label` argument to `_deal_card`, and derive winner/runner-ups from the already score-sorted `relevant` list. No JSON/CSV or scoring changes.

**Spec:** `docs/specs/2026-11-03-winner-first-report-design.md`

## Global Constraints

- Every deal appears once as a full card.
- Winner = highest score; runner-ups = next two in score order.
- Existing JSON/CSV/XLSX fields stay unchanged.
- Keep `Shops searched` and `Filtered out` at the end with links/reasons.
- Full suite must stay green; baseline 626 passed, 11 skipped.

## Task 1: Winner and runner-up cards

**Files:** modify `src/output/processor.py`, `tests/test_processor_details.py`.

- [ ] Write a failing test: a report with three analyses has `## Winner` before
  `## All found`, the winner title appears in both the winner card and the
  table, and the second/third deals appear in `## Runner-ups`.
- [ ] Run it; expect failure because the current report has no `## Winner`.
- [ ] Add `label` to `_deal_card`; print `**Pick:** <label>` when present.
- [ ] Derive `winner = relevant[0]`, `runnerups = relevant[1:3]`.
- [ ] Print `## Winner`, its full card, then `## Runner-ups` and their cards.
- [ ] Run the test; expect PASS.

## Task 2: All found, comparison, other deals

**Files:** modify `src/output/processor.py`, `tests/test_processor_details.py`.

- [ ] Write a failing test: `## All found` contains every relevant title once;
  `## Comparison` contains the top three; `## Other deals` contains only the
  remaining titles.
- [ ] Run it; expect failure.
- [ ] Rename the summary section to `## All found`; keep the table.
- [ ] Move the comparison table after `All found`; include winner + runner-ups.
- [ ] Replace `## Deal details` with `## Other deals`; render only deals not in
  the top three.
- [ ] Run the test; expect PASS.

## Task 3: Empty and filtered-out reports

**Files:** modify `src/output/processor.py`, `tests/test_processor_details.py`.

- [ ] Write failing tests: one relevant deal has no `## Runner-ups` section and
  no `## Other deals`; zero relevant deals still shows `No deals matching` and
  `## Filtered out` with a reason and link.
- [ ] Run them; expect failure on the new structure.
- [ ] Guard empty sections; keep the existing early return for zero deals.
- [ ] Run them; expect PASS.

## Task 4: Docs and verification

**Files:** modify `README.md`, `CHANGELOG.md`.

- [ ] Document the new report order.
- [ ] Run `python -m pytest -q`; expect 626+ passed, 11 skipped.
- [ ] Commit and push.
