"""Spec-based deal scoring for the replacement finder.

Scores a candidate deal against a reference ItemSpecs (researched in
Sub-project 1). Produces a 0-100 score with a per-criterion breakdown and
human-readable reasons.

Scoring criteria (weights, redistributed if a criterion is missing):
- Price match: 30%
- Power match: 20%
- Weight match: 10%
- Battery/range: 15%
- Condition: 15%
- Warranty: 5%
- Trust: 5%
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DealScore:
    """Score for one candidate deal against a reference item."""

    deal_url: str
    score: float = 0.0          # 0-100
    breakdown: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    matches_requirements: bool = True


@dataclass
class ScoringCriteria:
    """Weights for each scoring criterion (must sum to 100)."""

    price: float = 30.0
    power: float = 20.0
    weight: float = 10.0
    battery: float = 15.0
    condition: float = 15.0
    warranty: float = 5.0
    trust: float = 5.0


class DealScorer:
    """Scores candidate deals against reference ItemSpecs."""

    def __init__(self, criteria: ScoringCriteria | None = None):
        self.criteria = criteria or ScoringCriteria()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, deal, reference_specs: dict) -> DealScore:
        """Score *deal* against *reference_specs* (ItemSpecs as dict).

        Missing criteria are redistributed proportionally among present ones.
        """
        reference_specs = reference_specs or {}

        # Determine which criteria are applicable
        applicable = self._applicable_criteria(reference_specs, deal)
        total_weight = sum(applicable.values())
        if total_weight <= 0:
            return DealScore(
                deal_url=getattr(deal, "url", ""),
                score=0.0,
                reasons=["No applicable scoring criteria"],
            )

        # Compute per-criterion scores (0-100 each)
        criterion_scores: dict[str, float] = {}
        reasons: list[str] = []

        # Price match
        if applicable.get("price", 0) > 0:
            p_score, p_reason = self._score_price(deal, reference_specs)
            criterion_scores["price"] = p_score
            if p_reason:
                reasons.append(p_reason)

        # Power match
        if applicable.get("power", 0) > 0:
            pw_score, pw_reason = self._score_power(deal, reference_specs)
            criterion_scores["power"] = pw_score
            if pw_reason:
                reasons.append(pw_reason)

        # Weight match
        if applicable.get("weight", 0) > 0:
            w_score, w_reason = self._score_weight(deal, reference_specs)
            criterion_scores["weight"] = w_score
            if w_reason:
                reasons.append(w_reason)

        # Battery/range match
        if applicable.get("battery", 0) > 0:
            b_score, b_reason = self._score_battery(deal, reference_specs)
            criterion_scores["battery"] = b_score
            if b_reason:
                reasons.append(b_reason)

        # Condition
        if applicable.get("condition", 0) > 0:
            c_score, c_reason = self._score_condition(deal)
            criterion_scores["condition"] = c_score
            if c_reason:
                reasons.append(c_reason)

        # Warranty
        if applicable.get("warranty", 0) > 0:
            w_score, w_reason = self._score_warranty(deal)
            criterion_scores["warranty"] = w_score
            if w_reason:
                reasons.append(w_reason)

        # Trust
        if applicable.get("trust", 0) > 0:
            t_score, t_reason = self._score_trust(deal)
            criterion_scores["trust"] = t_score
            if t_reason:
                reasons.append(t_reason)

        # Weighted total
        weighted = sum(
            criterion_scores.get(k, 0.0) * (w / total_weight)
            for k, w in applicable.items()
        )
        score = round(weighted, 1)

        return DealScore(
            deal_url=getattr(deal, "url", ""),
            score=score,
            breakdown=criterion_scores,
            reasons=reasons,
            matches_requirements=score >= 50.0,
        )

    # ------------------------------------------------------------------
    # Per-criterion scorers
    # ------------------------------------------------------------------

    def _applicable_criteria(self, specs: dict, deal) -> dict[str, float]:
        """Return which criteria are applicable and their weights."""
        applicable = {}

        # Price: applicable if reference has price or deal has price
        ref_price = specs.get("price_eur")
        deal_price = self._deal_price(deal)
        if ref_price or deal_price:
            applicable["price"] = self.criteria.price

        # Power: applicable if reference has power_kw
        if specs.get("power_kw") or specs.get("power_hp"):
            applicable["power"] = self.criteria.power

        # Weight: applicable if reference has weight_kg
        if specs.get("weight_kg"):
            applicable["weight"] = self.criteria.weight

        # Battery/range: applicable if reference has battery_kwh or range_km (EV)
        if specs.get("battery_kwh") or specs.get("range_km"):
            applicable["battery"] = self.criteria.battery

        # Condition: always applicable
        applicable["condition"] = self.criteria.condition

        # Warranty: applicable if deal has warranty info
        if getattr(deal, "warranty", None) or getattr(deal, "seller_type", None):
            applicable["warranty"] = self.criteria.warranty

        # Trust: applicable if deal has price_quote
        if getattr(deal, "price_quote", None) is not None:
            applicable["trust"] = self.criteria.trust

        return applicable

    def _score_price(self, deal, specs: dict) -> tuple[float, str]:
        """Score price match (0-100). Within 10% = 100, within 30% = 50."""
        ref_price = specs.get("price_eur")
        deal_price = self._deal_price(deal)
        if not ref_price or not deal_price or ref_price <= 0:
            return 50.0, "Price not comparable"
        diff_pct = abs(deal_price - ref_price) / ref_price * 100
        if diff_pct <= 10:
            score = 100.0
        elif diff_pct <= 30:
            score = 100.0 - (diff_pct - 10) * 2.5
        else:
            score = max(0.0, 50.0 - (diff_pct - 30))
        reason = f"{deal_price:.0f} EUR vs reference {ref_price:.0f} EUR ({diff_pct:.0f}% diff)"
        return round(score, 1), reason

    def _score_power(self, deal, specs: dict) -> tuple[float, str]:
        """Score power match (0-100)."""
        ref_kw = specs.get("power_kw") or (specs.get("power_hp") or 0) * 0.7355
        deal_kw = self._deal_power_kw(deal)
        if not ref_kw or not deal_kw or ref_kw <= 0:
            return 50.0, "Power not comparable"
        diff_pct = abs(deal_kw - ref_kw) / ref_kw * 100
        if diff_pct <= 20:
            score = 100.0
        elif diff_pct <= 50:
            score = 100.0 - (diff_pct - 20) * 2.0
        else:
            score = max(0.0, 60.0 - (diff_pct - 50))
        reason = f"{deal_kw:.0f} kW vs reference {ref_kw:.0f} kW ({diff_pct:.0f}% diff)"
        return round(score, 1), reason

    def _score_weight(self, deal, specs: dict) -> tuple[float, str]:
        """Score weight match (0-100)."""
        ref_kg = specs.get("weight_kg")
        deal_kg = self._deal_weight_kg(deal)
        if not ref_kg or not deal_kg or ref_kg <= 0:
            return 50.0, "Weight not comparable"
        diff_pct = abs(deal_kg - ref_kg) / ref_kg * 100
        if diff_pct <= 20:
            score = 100.0
        elif diff_pct <= 50:
            score = 100.0 - (diff_pct - 20) * 1.5
        else:
            score = max(0.0, 70.0 - (diff_pct - 50))
        reason = f"{deal_kg:.0f} kg vs reference {ref_kg:.0f} kg ({diff_pct:.0f}% diff)"
        return round(score, 1), reason

    def _score_battery(self, deal, specs: dict) -> tuple[float, str]:
        """Score battery/range match for EVs (0-100)."""
        ref_kwh = specs.get("battery_kwh")
        ref_km = specs.get("range_km")
        deal_kwh = self._deal_battery_kwh(deal)
        deal_km = self._deal_range_km(deal)

        if not ref_kwh and not ref_km:
            return 50.0, "No reference battery/range"
        if not deal_kwh and not deal_km:
            return 30.0, "Candidate has no battery/range info"

        scores = []
        if ref_kwh and deal_kwh and ref_kwh > 0:
            diff_pct = abs(deal_kwh - ref_kwh) / ref_kwh * 100
            s = 100.0 if diff_pct <= 20 else max(0.0, 100.0 - diff_pct)
            scores.append(s)
        if ref_km and deal_km and ref_km > 0:
            diff_pct = abs(deal_km - ref_km) / ref_km * 100
            s = 100.0 if diff_pct <= 20 else max(0.0, 100.0 - diff_pct)
            scores.append(s)

        score = sum(scores) / len(scores) if scores else 50.0
        parts = []
        if deal_kwh:
            parts.append(f"{deal_kwh} kWh")
        if deal_km:
            parts.append(f"{deal_km} km")
        reason = f"Battery/range: {', '.join(parts)} vs reference "
        if ref_kwh:
            reason += f"{ref_kwh} kWh"
        if ref_km:
            reason += f" / {ref_km} km"
        return round(score, 1), reason

    def _score_condition(self, deal) -> tuple[float, str]:
        """Score condition preference (new > refurbished > used)."""
        condition = (getattr(deal, "condition", None) or "unknown").lower()
        scores = {
            "new": 100.0,
            "refurbished": 70.0,
            "open_box": 85.0,
            "used": 40.0,
            "unknown": 50.0,
        }
        score = scores.get(condition, 50.0)
        reason = f"Condition: {condition}"
        return score, reason

    def _score_warranty(self, deal) -> tuple[float, str]:
        """Score warranty availability."""
        warranty = getattr(deal, "warranty", None) or ""
        seller_type = getattr(deal, "seller_type", "") or ""
        if warranty or seller_type in ("retailer", "marketplace"):
            score = 100.0
            reason = f"Warranty: {warranty or seller_type}"
        else:
            score = 30.0
            reason = "No warranty info"
        return score, reason

    def _score_trust(self, deal) -> tuple[float, str]:
        """Score from PriceQuote trust (0-1 -> 0-100)."""
        quote = getattr(deal, "price_quote", None)
        if quote is not None and hasattr(quote, "trust"):
            trust = quote.trust or 0.0
            score = trust * 100.0
            reason = f"Trust: {trust:.2f}"
        else:
            score = 50.0
            reason = "No price quote"
        return score, reason

    # ------------------------------------------------------------------
    # Deal field extractors
    # ------------------------------------------------------------------

    def _deal_price(self, deal) -> float | None:
        quote = getattr(deal, "price_quote", None)
        if quote is not None and hasattr(quote, "effective_price_eur") and quote.effective_price_eur > 0:
            return float(quote.effective_price_eur)
        price = getattr(deal, "price_eur", None)
        return float(price) if price else None

    def _deal_power_kw(self, deal) -> float | None:
        extras = getattr(deal, "metadata", {}) or {}
        if isinstance(extras, str):
            try:
                import json
                extras = json.loads(extras)
            except (json.JSONDecodeError, TypeError):
                extras = {}
        price_quote = extras.get("price_quote", {}) if isinstance(extras, dict) else {}
        # Power may be in extras as power_kw
        if isinstance(extras, dict) and extras.get("power_kw"):
            try:
                return float(extras["power_kw"])
            except (ValueError, TypeError):
                pass
        return None

    def _deal_weight_kg(self, deal) -> float | None:
        extras = getattr(deal, "metadata", {}) or {}
        if isinstance(extras, str):
            try:
                import json
                extras = json.loads(extras)
            except (json.JSONDecodeError, TypeError):
                extras = {}
        if isinstance(extras, dict) and extras.get("weight_kg"):
            try:
                return float(extras["weight_kg"])
            except (ValueError, TypeError):
                pass
        return None

    def _deal_battery_kwh(self, deal) -> float | None:
        extras = getattr(deal, "metadata", {}) or {}
        if isinstance(extras, str):
            try:
                import json
                extras = json.loads(extras)
            except (json.JSONDecodeError, TypeError):
                extras = {}
        if isinstance(extras, dict) and extras.get("battery_kwh"):
            try:
                return float(extras["battery_kwh"])
            except (ValueError, TypeError):
                pass
        return None

    def _deal_range_km(self, deal) -> float | None:
        extras = getattr(deal, "metadata", {}) or {}
        if isinstance(extras, str):
            try:
                import json
                extras = json.loads(extras)
            except (json.JSONDecodeError, TypeError):
                extras = {}
        if isinstance(extras, dict) and extras.get("range_km"):
            try:
                return float(extras["range_km"])
            except (ValueError, TypeError):
                pass
        return None
