# Design: CLI Wizard & Automation (Sub-project 4)

**Date:** 2026-11-05  
**Deep research goal:** User experience & automation (CLI wizard, scheduling, notifications)  
**Status:** Draft  

## Problem

The `find-replacement` command (Sub-project 3) is non-interactive — the user must know all flags upfront. For non-technical users, an interactive CLI wizard is needed that guides them through: item → category → condition → price range → results.

The deep research goals also mention scheduling (daily/weekly monitoring) and notification strategies. The existing `monitor`/`watch` commands handle this partially but aren't integrated with the replacement finder.

## Scope

**In scope:**

1. **Interactive CLI wizard** — `ads find-replacement --interactive` (or just `ads find-replacement` without `--item`):
   - Prompt for item name (with examples)
   - Prompt for category (numbered list: auto, electronics, appliances, home, hobby, general)
   - Prompt for condition (new/used/refurbished/open_box/any)
   - Prompt for max price (optional)
   - Confirm before running
   - Show progress during research/search/scoring
   - Display results in a readable format

2. **Notification integration** — price drop alerts from Sub-project 3's price tracking are sent via notification channels (console, email, webhook, discord, system) when running `find-replacement`

3. **Scheduling hook** — `ads find-replacement --item X --schedule daily` saves the search as a scheduled job (reuses existing scheduler infrastructure)

**Out of scope (Sub-project 5):**
- Web dashboard
- Parallel search architecture changes
- Plugin system

## Architecture

```
src/cli/wizard.py              (new) — Interactive prompts using built-in input()
  ├── prompt_item() -> str
  ├── prompt_category() -> str
  ├── prompt_condition() -> str
  ├── prompt_price_range() -> tuple
  ├── confirm() -> bool
  └── run_wizard() -> dict

src/cli/app.py                 (modify) — --interactive flag on find-replacement
  └── find-replacement --interactive calls wizard then runs pipeline
```

## User states

| State | What user sees |
|-------|---------------|
| First run, no data | Wizard prompts step by step, examples shown |
| Invalid input | Re-prompt with error message |
| Search in progress | "Researching specs...", "Searching sites...", "Scoring candidates..." |
| No results | "No matching alternatives found. Try broadening criteria." |
| Results found | Ranked list with winner, scores, reasons |

## Error handling

- Invalid category: re-prompt with valid options
- Invalid price: re-prompt with error
- Search fails: show error, offer to retry with broader criteria
- LLM unavailable: use deterministic fallback, continue

## Testing

- Unit tests for wizard prompts (mocked input)
- Integration test: wizard → find-replacement flow
- Full suite must remain green (713 passed, 11 skipped baseline)

## Files to create/modify

**Create:**
- `src/cli/wizard.py`
- `tests/test_wizard.py`

**Modify:**
- `src/cli/app.py` — add --interactive flag to find-replacement

## Design decisions

- **Built-in input()**: no new dependencies, works on all platforms
- **Numbered lists**: easier than typing exact category names
- **Progress messages**: reassure user the tool is working
- **Examples in prompts**: "e.g. Citroen eC3, Tesla Model 3, iPhone 15"
