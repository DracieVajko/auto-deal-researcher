# Design: Price Alert Thresholds with Notification Delivery (Sub-project 6)

**Date:** 2026-11-06  
**Source:** `docs/specs/2026-11-06-deep-research-analysis.md` (selected next implementation)  
**Status:** Draft — proceeding to implementation per "run until finished" instruction

## Problem

Price tracking already detects drops/new-lows/fake-promos, but users cannot set a **target price** and get notified when a specific item/URL drops to or below it. The documentation roadmap (`dokumentacia.txt` §13) lists "Price alert thresholds — notifikácia pri poklese pod X€" as a desired feature. Without it, users must re-run searches and manually compare prices.

## Scope

**In scope:**
- `PriceAlertRule` dataclass: `url`, `title`, `target_price_eur`, `condition`, `channels`, `cooldown_minutes`, `added_at`, `last_triggered`, `is_active`.
- SQLite `alert_rules` table (migration to SCHEMA_VERSION 6): url (UNIQUE), target_price_eur, condition, channels, cooldown_minutes, added_at, last_triggered, is_active.
- `StorageManager.save_price_alert_rule`, `get_price_alert_rule`, `list_price_alert_rules`, `remove_price_alert_rule`, `set_rule_active/inactive`.
- `AlertRuleEngine.evaluate_rules()`: for each active rule, fetch the latest effective price for the URL; if `<= target_price_eur` and cooldown elapsed, create an `Alert`.
- CLI: `ads alert-rule add --url ... --target-price ... [--condition ...] [--channels ...]`, `ads alert-rule list`, `ads alert-rule remove --url ...`, `ads alert-rule enable/disable --url ...`.
- Integration: after each `run`/`monitor`, evaluate active rules and send triggered alerts via `NotificationManager`.
- Notification: `Alert` with `severity="info"`, message includes URL, title, target price, current price, savings.

**Out of scope:**
- Price-history charts (already exist).
- Web dashboard (deferred per research priority).
- Saved searches/profiles (deferred).

## Architecture

```
src/storage/manager.py        — alert_rules CRUD (SQLite table)
src/intelligence/price_tracker.py — AlertRuleEngine.evaluate_rules() → list[Alert]
src/cli/app.py                — alert-rule commands + integration into run/monitor
src/notifications/manager.py  — NotificationManager.send_alert (already exists)
```

Data flow per search run:
1. Search runs, deals saved with effective_price_eur.
2. After save, `AlertRuleEngine(storage, notification_manager).evaluate_all_rules()`.
3. For each rule: `StorageManager.get_latest_effective_price(url)` → compare to target → if triggered and cooldown OK → `NotificationManager.send_alert(alert)` → update `last_triggered`.

## Data model

```sql
CREATE TABLE alert_rules (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    target_price_eur REAL NOT NULL,
    condition TEXT DEFAULT 'any',
    channels TEXT DEFAULT '[]',   -- JSON list of channel names
    cooldown_minutes INTEGER DEFAULT 60,
    added_at TEXT NOT NULL,
    last_triggered TEXT,
    is_active INTEGER DEFAULT 1
);
```

```python
@dataclass
class PriceAlertRule:
    url: str
    title: str
    target_price_eur: float
    condition: str = "any"
    channels: list[str] = field(default_factory=list)
    cooldown_minutes: int = 60
    added_at: str = ""
    last_triggered: str | None = None
    is_active: bool = True
```

## Error handling
- Rule for a URL that has never been searched: skip (no price yet), log debug.
- Cooldown not elapsed: skip, log debug.
- Notification channel failure: log warning, continue with other rules/channels.
- Invalid target price (<=0): reject at CLI with clear error.

## Testing
- Unit tests: rule insert/update/get/list/remove; activate/deactivate.
- `AlertRuleEngine.evaluate_rules`: trigger when current <= target; no trigger when current > target; cooldown blocks re-trigger within window; inactive rule skipped; no price yet skipped.
- Integration: run search → rules evaluated → alerts sent (mocked notification channel).
- Full suite must remain green (742 passed, 11 skipped baseline).

## Files to create/modify

**Create:**
- `tests/test_price_alert_rules.py`

**Modify:**
- `src/storage/schema.py` — SCHEMA_VERSION 6, ALERT_RULES_COLUMNS, migration 006.
- `src/storage/manager.py` — alert rule CRUD methods + `get_latest_effective_price`.
- `src/intelligence/price_tracker.py` — `AlertRuleEngine`.
- `src/cli/app.py` — `alert-rule` commands + post-run integration.
- `docs/specs/2026-11-06-price-alert-thresholds-design.md` — this file.

## Design decisions
- **url as primary key**: one rule per URL; a user watching the same item gets one rule.
- **channels default `[]`**: if empty, use all configured notification channels (fallback in engine).
- **Effective price (not raw)** for threshold comparison — consistent with price trust work.
- **Cooldown per rule** prevents spam on oscillating prices.
