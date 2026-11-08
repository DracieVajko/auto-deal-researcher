# Design: Enum-typed Condition/Category comparisons (follow-up to Task 1)

- Date: 2026-11-08
- Status: implemented
- Cluster: type-safety-enums-and-literals (follow-up; reopened finding)
- Detector: review — `holistic::abstraction_fitness::enum_bypass_raw_strings`

## Context

Desloppify reopened the enum-bypass finding
(`Condition/Category membership checks compare raw strings instead of enum
members`). Task 1 (`58333ec`) fixed `Deal.matches_condition` / `matches_category`
and typed several boundaries as `Condition | str`, but raw-string membership
checks kept reappearing:

- `src/searcher/adapters/base.py` — `matches_condition` / `matches_category`
  compared incoming values against the literal `"any"`.
- `src/searcher/filter_engine.py` — category URL selection compared against `"any"`.
- `src/intelligence/price_tracker.py` — condition filtering compared against `"any"`.
- `src/agents/research/site_selection.py` — capability matching compared against `"any"`.
- `src/cli/app.py` — category validation / brief rendering compared against `"any"`.

## Decision

All condition/category membership checks compare against the `StrEnum` members
`Condition.ANY` / `Category.ANY` instead of the raw strings `"any"`. Boundary
parameters keep accepting `Condition | str` / `Category | str` so callers may pass
either form; `StrEnum` equality is value-based, so `"any" == Condition.ANY` is `True`
and behavior is unchanged.

## Consequences

- Typing tightened at the comparison sites; no behavior change expected.
- Tests added in `tests/test_enum_comparisons.py`, `tests/test_filter_engine.py` and
  condition-filter coverage to lock enum-vs-string equivalence.
- Remaining known raw-string defaults (e.g. `condition: str = "any"` CLI option
  defaults) are tracked separately as migration cleanup.
