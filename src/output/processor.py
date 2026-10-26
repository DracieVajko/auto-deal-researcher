"""Result processor: JSON + Markdown reports with per-deal analysis.

The plain report used to answer only "what was found". This processor adds
the information a buyer actually needs: whether the listing is the right
product type, a score with a visible breakdown, pros and cons, known specs,
alternatives, and what to verify before paying.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from src.config.models import OutputConfig
from src.output.dedup import collapse_duplicates
from src.output.domains import DomainProfile, detect, get
from src.output.domains.ai import proposal_to_profile, propose_domain
from src.output.domains.cache import AI_DRAFT_DIR, load_drafts, save_draft
from src.output.requirements import (
    apply_requirement_guard,
    extract_requirements,
    has_hard_defect,
)
from src.searcher.adapters.base import Deal
from src.searcher.listing_filter import is_laptop_title, wants_mini_pc_form_factor
from src.text.normalize import fold
from src.utils.time import utcnow_stamp

logger = logging.getLogger(__name__)

CONDITION_LABELS = {
    "new": "New",
    "used": "Used",
    "refurbished": "Refurbished",
    "open_box": "Open box",
    "unknown": "Unknown",
}

SELLER_LABELS = {
    "retailer": "Retailer",
    "marketplace": "Marketplace",
    "classifieds": "Private seller (classifieds)",
    "auction": "Auction",
}

VERDICT_LABELS = {
    "buy": "✅ Good buy",
    "watch": "⚠️ Watch",
    "skip": "⛔ Skip",
}

ANALYSIS_CHUNK = 8


@dataclass
class DealAnalysis:
    """One listing plus the reasoning needed to compare it with the others."""

    deal: Deal
    score: float = 0.0
    llm_score: float | None = None
    verdict: str = "watch"
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    specs: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    is_laptop: bool = False
    wrong_form_factor: bool = False
    matches_requirements: bool = True
    score_breakdown: dict[str, float] = field(default_factory=dict)
    seller_type: str = ""
    warranty: str = ""
    spec_coverage: dict[str, list[str]] = field(default_factory=dict)
    domain: str = "generic"
    # The exact profile that detected this domain, including an AI draft that
    # is not in DOMAIN_REGISTRY. Consumers resolve `profile or get(domain)`.
    profile: DomainProfile | None = None


class ResultProcessor:
    # Scoring rows every domain has, and the one row only computer enables.
    # A breakdown that omits Connectivity is normalised over 0.95 so a domain
    # without the row still reaches 100.
    BASE_WEIGHTS: ClassVar[dict[str, float]] = {
        "Requirement fit": 0.30,
        "Spec match": 0.25,
        "Price": 0.20,
        "Condition & warranty": 0.10,
        "Seller trust": 0.10,
    }
    CONNECTIVITY_WEIGHT: ClassVar[float] = 0.05
    # A price judgement needs a sample; three listings are not a market.
    MIN_PRICE_SAMPLE: ClassVar[int] = 4
    # The report computes the Price row; the model must not invent one.
    _PRICE_CLAIM_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"\b(?:above|below|over|under)\s+(?:the\s+)?(?:market|reasonable)\b"
        r"|\bmarket\s+value\b|\boverpriced\b|\bprice\s+far\s+exceeds\b",
        re.IGNORECASE,
    )

    def __init__(self, config, llm=None):
        self.config: OutputConfig = config.output
        self.full_config = config
        self.llm = llm
        # --domain / output.domain from the CLI; None means auto-detect.
        # The CLI value overrides this one when it is given.
        self.domain_override = getattr(self.config, "domain", "") or None
        # Where AI drafts are cached; a test may point it at a temp dir.
        self.draft_dir = AI_DRAFT_DIR
        # Determine user's preferred output currency
        self.output_currency = (
            getattr(getattr(self.full_config, "search", None), "default_currency", "") or ""
        ).upper() or "EUR"

    def _format_price(self, deal) -> tuple[float, str]:
        """Convert deal price to user's preferred output currency."""
        if deal.price_eur <= 0:
            return 0.0, self.output_currency
        if self.output_currency == "EUR":
            return deal.price_eur, "EUR"
        # Convert from EUR to target currency
        rates = getattr(getattr(self.full_config, "search", None), "currency_rates", {})
        rate = rates.get(self.output_currency, 1.0)
        if rate <= 0:
            rate = 1.0
        return deal.price_eur / rate, self.output_currency

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def save_results(
        self,
        deals: list[Deal],
        output_dir: str | None = None,
        prompt: str | None = None,
    ) -> tuple[str, str]:
        """Write one JSON file and one Markdown file.

        The file name is ``results_<timestamp>_<slug>`` where the slug is a
        short AI-generated description of what was searched, so runs are
        identifiable at a glance instead of being a bare timestamp.
        """
        timestamp = utcnow_stamp()
        slug = await self._describe_search_async(prompt)
        stem = f"results_{timestamp}_{slug}" if slug else f"results_{timestamp}"

        out_dir = Path(output_dir or self.config.directory)
        out_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - tiny CLI, not a server

        # The same item posted twice must not double-count in the median or
        # take two places in the report.
        deals, duplicates_collapsed = collapse_duplicates(deals)

        analyses = await self._analyze_deals(deals, prompt)
        relevant = [a for a in analyses if not a.wrong_form_factor]
        filtered = [a for a in analyses if a.wrong_form_factor]
        # Best overall deal first: the summary must agree with the scores
        # instead of keeping an arbitrary search order.
        relevant.sort(key=lambda analysis: analysis.score, reverse=True)

        top_n = getattr(getattr(self.full_config, "search", None), "winners_count", 3)
        top_picks: set[str] = set()
        for analysis in relevant:
            if analysis.verdict == "skip":
                continue
            top_picks.add(analysis.deal.url)
            if len(top_picks) >= top_n:
                break

        json_path = out_dir / f"{stem}.json"
        payload = {
            "prompt": prompt or "",
            "generated_at": timestamp,
            "count": len(relevant),
            "duplicates_collapsed": duplicates_collapsed,
            "filtered_out_count": len(filtered),
            "deals": [
                self._deal_to_dict(
                    analysis,
                    rank=index,
                    is_top_pick=analysis.deal.url in top_picks,
                )
                for index, analysis in enumerate(relevant, 1)
            ],
            "filtered_out": [
                {
                    "title": a.deal.title,
                    "site_name": a.deal.site_name,
                    "price_eur": a.deal.price_eur,
                    "url": a.deal.url,
                    "reason": "Form factor does not match the request",
                }
                for a in filtered
            ],
        }
        with open(json_path, "w", encoding="utf-8") as handle:  # noqa: ASYNC230
            json.dump(payload, handle, indent=2, ensure_ascii=False)

        md_content = self._to_markdown(prompt, relevant, filtered, timestamp, top_picks)
        md_path = out_dir / f"{stem}.md"
        with open(md_path, "w", encoding="utf-8") as handle:  # noqa: ASYNC230
            handle.write(md_content)

        if filtered:
            logger.info(
                "Filtered %d laptop/notebook listing(s) from the report",
                len(filtered),
            )
        return str(json_path), str(md_path)

    # ------------------------------------------------------------------
    # Naming
    # ------------------------------------------------------------------
    async def _describe_search_async(self, prompt: str | None) -> str:
        """Short kebab-case slug describing the search, from the LLM if possible."""
        if not prompt:
            return ""

        raw = None
        if self.llm is not None:
            try:
                raw = await self.llm._filename_slug_async(prompt)
            except Exception as exc:  # noqa: BLE001 - naming must never break a run
                logger.debug("Slug generation failed: %s", exc)

        if not raw:
            try:
                from src.llm.client import LLMClient

                raw = LLMClient.keyword_query(prompt, max_words=4)
            except Exception:  # noqa: BLE001 - slug fallback is best-effort
                raw = prompt

        return self._slugify(raw)

    @staticmethod
    def _slugify(text: str, max_words: int = 5, max_len: int = 48) -> str:
        """Reduce arbitrary text to a safe file-name slug."""
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r"[^a-z0-9]+", "-", text)
        text = re.sub(r"-{2,}", "-", text).strip("-")
        words = [word for word in text.split("-") if word][:max_words]
        slug = "-".join(words)
        if len(slug) > max_len:
            slug = slug[:max_len].rstrip("-")
        return slug

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------
    async def _analyze_deals(
        self, deals: list[Deal], prompt: str | None
    ) -> list[DealAnalysis]:
        if not deals:
            return []

        analyses = [self._heuristic_analysis(deal, prompt) for deal in deals]

        await self._apply_domain_fallbacks(analyses, prompt)

        if self.llm is not None:
            for start in range(0, len(analyses), ANALYSIS_CHUNK):
                chunk = analyses[start : start + ANALYSIS_CHUNK]
                try:
                    enriched = await self._llm_analyze_batch(chunk, prompt)
                except Exception as exc:  # noqa: BLE001 - heuristics are the fallback
                    logger.warning("LLM deal analysis failed: %s", exc)
                    enriched = []

                # Preferred: match on the explicit listing id. Small models
                # copy "L3" reliably even when they reorder objects or get
                # the numeric index wrong.
                ids = [self._analysis_id(item.get("id")) for item in enriched]
                by_id = {
                    listing_id: item
                    for listing_id, item in zip(ids, enriched, strict=True)
                    if listing_id
                }
                expected = {f"L{index}" for index in range(len(chunk))}
                if len(set(ids)) == len(ids) and expected.issubset(by_id):
                    for index, analysis in enumerate(chunk):
                        self._merge_llm_analysis(
                            analysis, by_id[f"L{index}"], prompt
                        )
                elif len(enriched) == len(chunk):
                    # Positional merge: the prompt promises one object per
                    # listing, in the same order.
                    for analysis, item in zip(chunk, enriched, strict=True):
                        self._merge_llm_analysis(analysis, item, prompt)
                else:
                    for item in enriched:
                        index = item.get("index")
                        if isinstance(index, int) and 0 <= index < len(chunk):
                            self._merge_llm_analysis(chunk[index], item, prompt)

        self._add_cross_alternatives(analyses)
        return analyses

    async def _apply_domain_fallbacks(
        self, analyses: list[DealAnalysis], prompt: str | None
    ) -> None:
        """Second-chance detection for listings the registry left generic.

        Order is spec section 5.3: cached drafts before one live proposal.
        An explicit `--domain` override already won in `_heuristic_analysis`
        and is never replaced here.
        """
        unknown: list[tuple[DealAnalysis, str]] = []
        drafts = {} if self.domain_override else load_drafts(self.draft_dir)
        for analysis in analyses:
            if analysis.domain != "generic":
                continue
            folded = fold(
                f"{analysis.deal.title} "
                f"{json.dumps(analysis.deal.metadata, ensure_ascii=False)}"
            )
            profile = detect(folded, extra=drafts.values())
            if profile.name != "generic":
                analysis.domain = profile.name
                analysis.profile = profile
                analysis.specs = profile.extract(folded)
            else:
                unknown.append((analysis, folded))

        if not unknown or self.llm is None:
            return

        # V1: one live proposal per run, for the first unknown listing only.
        source, source_text = unknown[0]
        proposal = await propose_domain(self.llm, source_text, prompt)
        if proposal is None:
            return
        profile = proposal_to_profile(proposal)
        if profile.matches(source_text) == 0:
            # A draft that cannot even name the listing that produced it is
            # write-only: it would pollute the cache without ever matching.
            # Keep the listing generic and leave the cache clean.
            logger.warning(
                "AI domain proposal %s missed its own listing; discarded",
                proposal.domain,
            )
            return
        try:
            save_draft(proposal, source.deal.title, self.draft_dir)
        except OSError as exc:  # a cache miss must not break the run
            logger.warning("could not cache AI domain draft: %s", exc)
        for analysis, folded in unknown:
            # Apply the proposal only to listings that match its own keywords;
            # a sofa must not borrow a camera's vocabulary.
            if profile.matches(folded) > 0:
                analysis.domain = profile.name
                analysis.profile = profile
        if profile.matches(source_text) > 0:
            # proposal.specs describe the listing that was sent, not the others.
            for key, value in profile.normalise_specs(proposal.specs).items():
                source.specs.setdefault(key, value)

    async def _llm_analyze_batch(
        self, analyses: list[DealAnalysis], prompt: str | None
    ) -> list[dict]:
        """One LLM call for a small batch of listings.

        Batching keeps the cost predictable: a 20-result run needs three calls
        instead of twenty, and the model can compare listings to each other.
        """
        lines = []
        for index, analysis in enumerate(analyses):
            deal = analysis.deal
            seller = analysis.seller_type or "unknown"
            line = (
                f"[L{index}] {deal.title} | {deal.price_eur:.0f} EUR | "
                f"{deal.condition} | {deal.site_name} | seller: {seller} | "
                f"specs: {json.dumps(analysis.specs, ensure_ascii=False)}"
            )
            # The seller's own description is where frame size, fork type and
            # defects are stated. Keep it short so the prompt stays predictable.
            if deal.metadata.get("detail_failed") or deal.metadata.get("detail_skipped"):
                line += " | description: not fetched"
            else:
                description = " ".join(
                    str(deal.metadata.get("description") or "").split()
                )
                if description:
                    line += f" | description: {description[:600]}"
            profile = analysis.profile or get(analysis.domain)
            if profile.key_specs:
                line += " | track these specs: " + ", ".join(profile.key_specs)
            lines.append(line)

        pc_mode = any(analysis.domain == "computer" for analysis in analyses)
        system = (
            "You are a strict second-hand product buyer. Evaluate listings "
            "against the user's request. Use ONLY the information in the listing: "
            "never invent specifications, condition, warranty or defects. Return "
            "exactly one JSON object per listing, in the same order, wrapped in a "
            "JSON array. No prose, no markdown fences."
        )
        rules = [
            '- Copy the listing id (L0, L1, ...) exactly into "id".',
            "- Return one object for every listing, including ones you reject.",
            "- If the listing is not the product the user asked for (a part, an "
            "accessory, a different kind of item), verdict 'skip', score <= 25.",
            "- A used listing is not a defect by itself; judge condition and seller.",
            '- When the request says "A or B", either one satisfies it; never report '
            "the missing one as a defect.",
            "- If a specification is not stated, say 'not stated'. Never claim a "
            "specification is wrong when the listing does not mention it.",
            "- When a listing says its description was not fetched, do not claim "
            "a specification is not stated; say it could not be checked.",
            "- Do not say a price is above or below market; you do not know the "
            "market. The report computes the price score itself.",
            "- Use only the spec keys listed for that listing and omit a key "
            "the listing does not state; when no keys are listed, use short "
            "snake_case keys for facts stated in the listing. Never invent values.",
            "- price_eur is the asking price in EUR.",
            "- Alternatives: at most 2 real, commonly available alternatives worth "
            "considering instead of this listing.",
            "- score is 0-100 for fit to the request, value for money and risk.",
            "- Keep pros and cons to 2-4 short items each.",
        ]
        if pc_mode:
            rules += [
                "- Wrong product type (a laptop when a mini PC/barebone was "
                "requested, a part, an accessory, a monitor) => verdict 'skip', "
                "score <= 25.",
                "- A barebone normally ships without RAM and SSD; treat that as a "
                "cost to budget, not a disqualifier.",
                "- The search already verified the product category. Do not claim "
                "the listing is not a mini PC/barebone; judge the stated specs "
                "instead.",
            ]
        user = (
            f"User request: {prompt or 'find good deals'}\n\n"
            "Listings:\n" + "\n".join(lines) + "\n\n"
            "Schema per listing:\n"
            '{"id": "L0", "index": 0, "score": 0, "verdict": "buy|watch|skip", '
            '"matches_requirements": true, "pros": ["..."], "cons": ["..."], '
            '"specs": {"key": "value"}, '
            '"alternatives": [{"title": "...", "approx_price_eur": 0, "why": "..."}], '
            '"notes": "one sentence"}\n\n'
            "Rules:\n" + "\n".join(rules)
        )
        response = await self.llm._chat(
            system,
            user,
            max_tokens=3000,
            temperature=0.0,
        )
        return self._parse_analysis_json(response)

    @staticmethod
    def _parse_analysis_json(response: str) -> list[dict]:
        """Extract the JSON array from a model reply, tolerating fences/prose."""
        if not response:
            return []
        text = response.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            logger.debug("Deal analysis JSON parse failed: %s", exc)
            return []
        return [item for item in data if isinstance(item, dict)]

    @staticmethod
    def _analysis_id(value) -> str:
        """Normalize a model-supplied listing id such as ``l3`` to ``L3``."""
        match = re.search(r"L\s*(\d+)", str(value or ""), re.IGNORECASE)
        return f"L{match.group(1)}" if match else ""

    @staticmethod
    def _tidy_text(text: str) -> str:
        """Normalize common model typos in hardware names."""
        return re.sub(r"\bOC\.?\s*uLink\b", "OCuLink", text, flags=re.IGNORECASE)

    def _merge_llm_analysis(
        self, analysis: DealAnalysis, data: dict, prompt: str | None
    ) -> None:
        score = data.get("score")
        if isinstance(score, (int, float)):
            analysis.llm_score = max(0.0, min(100.0, float(score)))
            analysis.score = analysis.llm_score

        verdict = str(data.get("verdict", "")).lower().strip()
        if verdict in VERDICT_LABELS:
            analysis.verdict = verdict

        if data.get("matches_requirements") is False:
            analysis.matches_requirements = False
        if data.get("is_laptop") is True:
            analysis.is_laptop = True
            if wants_mini_pc_form_factor(prompt):
                analysis.wrong_form_factor = True

        for key, attr in (("pros", "pros"), ("cons", "cons")):
            values = data.get(key)
            if isinstance(values, list):
                cleaned = []
                for value in values:
                    text = self._tidy_text(str(value).strip())
                    if not text:
                        continue
                    low = text.casefold()
                    # "Used condition" is not a benefit; bare condition labels
                    # are already covered by the deterministic section.
                    if low in {
                        "new condition",
                        "used condition",
                        "refurbished condition",
                        "unknown",
                    }:
                        continue
                    if key == "pros" and any(
                        marker in low
                        for marker in ("no warranty", "not included", "not specified")
                    ):
                        continue
                    if key == "cons" and self._PRICE_CLAIM_RE.search(low):
                        continue
                    cleaned.append(text)
                if cleaned:
                    merged = self._append_unique(getattr(analysis, attr), cleaned)
                    setattr(analysis, attr, merged)

        # The deterministic layer reads the listing itself; if a required spec
        # is stated and satisfies the request, a model claim of "not stated"
        # is a wrong fact, not a judgement. Drop it — but only facts: a hard
        # defect stays a rejection for its own reason.
        requirements = extract_requirements(prompt or "")
        kept, rescued = apply_requirement_guard(
            analysis.cons, analysis.specs, requirements
        )
        if rescued:
            analysis.cons = kept
            if not has_hard_defect(kept):
                analysis.matches_requirements = True

        specs = data.get("specs")
        if isinstance(specs, dict):
            unknown = {
                "",
                "unknown",
                "n/a",
                "na",
                "none",
                "null",
                "not specified",
                "not stated",
            }
            filtered: dict[str, str] = {}
            for key, value in specs.items():
                if value is None:
                    continue
                text = self._tidy_text(str(value).strip())
                if text.casefold() in unknown:
                    continue
                filtered[str(key)] = text

            # Map through aliases, keep only the domain's vocabulary and never
            # a second price. A generic profile has no vocabulary to enforce.
            profile = analysis.profile or get(analysis.domain)
            for key, value in profile.normalise_specs(filtered).items():
                # The deterministic parser reads the listing itself; the model
                # may fill gaps but must not overwrite a verified value.
                analysis.specs.setdefault(key, value)

        alternatives = data.get("alternatives")
        if isinstance(alternatives, list):
            parsed = []
            for alt in alternatives[:3]:
                if not isinstance(alt, dict):
                    continue
                title = self._tidy_text(str(alt.get("title", "")).strip())
                if not title:
                    continue
                price = alt.get("approx_price_eur", alt.get("price_eur"))
                parsed.append(
                    {
                        "title": title,
                        "price_eur": price if isinstance(price, (int, float)) else None,
                        "why": self._tidy_text(
                            str(alt.get("why", alt.get("reason", ""))).strip()
                        ),
                        "source": "llm",
                    }
                )
            if parsed:
                analysis.alternatives = parsed

        notes = data.get("notes")
        if isinstance(notes, str) and notes.strip():
            analysis.notes = self._tidy_text(notes.strip())

        if analysis.wrong_form_factor:
            analysis.score = min(analysis.score, 20.0)
            analysis.matches_requirements = False
            analysis.verdict = "skip"

    @staticmethod
    def _append_unique(existing: list[str], new_items: list[str], limit: int = 6) -> list[str]:
        """Merge two short bullet lists without repeating the same fact."""

        def normalized(text: str) -> str:
            text = text.casefold()
            text = re.sub(r"(?<=\d)(?=[a-z])", " ", text)
            return re.sub(r"[^a-z0-9]+", " ", text).strip()

        def missing_component(text: str) -> str | None:
            low = normalized(text)
            if not any(
                token in low
                for token in (
                    "no ",
                    "not ",
                    "without",
                    "bez ",
                    "unknown",
                    "not stated",
                    "not specified",
                )
            ):
                return None
            if re.search(r"\b(cpu|processor|ryzen|intel core)\b", low):
                return "cpu"
            if re.search(r"\b(ram|memory|so dimm)\b", low):
                return "ram"
            if re.search(r"\b(ssd|storage|nvme|disk)\b", low):
                return "storage"
            if re.search(r"\b(gpu|graphics)\b", low):
                return "gpu"
            if re.search(r"\b(thunderbolt|oculink|usb4|connectivity|ports?)\b", low):
                return "connectivity"
            return None

        def similar(first: str, second: str) -> bool:
            first_tokens = set(first.split())
            second_tokens = set(second.split())
            if not first_tokens or not second_tokens:
                return False
            return len(first_tokens & second_tokens) / len(
                first_tokens | second_tokens
            ) >= 0.5

        kept = list(existing)
        seen = [normalized(item) for item in kept]
        covered = {missing_component(item) for item in kept}

        for item in new_items:
            candidate = normalized(item)
            if not candidate:
                continue
            if any(
                candidate in other or other in candidate or similar(candidate, other)
                for other in seen
            ):
                continue
            component = missing_component(item)
            if component is not None and component in covered:
                continue
            kept.append(item)
            seen.append(candidate)
            covered.add(component)
            if len(kept) >= limit:
                break
        return kept

    def _heuristic_analysis(self, deal: Deal, prompt: str | None) -> DealAnalysis:
        """Baseline analysis that works without any LLM."""
        seller_type, warranty = self._site_trust(deal)
        laptop = is_laptop_title(deal.title)
        text = fold(f"{deal.title} {json.dumps(deal.metadata, ensure_ascii=False)}")

        profile = detect(text, override=self.domain_override)
        if profile.name == "generic" and laptop:
            # A laptop title is a computer even when it names no PC keyword.
            profile = get("computer")
        specs = profile.extract(text)
        wrong_form = (
            laptop
            and profile.name == "computer"
            and wants_mini_pc_form_factor(prompt)
        )

        matches = self._matches_prompt(prompt, deal, profile.name, specs, wrong_form)
        messages, disqualify = profile.check(specs, prompt)
        if disqualify:
            matches = False
        pros, cons = self._heuristic_pros_cons(
            deal, prompt, specs, seller_type, wrong_form, laptop, profile.name
        )
        cons.extend(messages)

        score = 50.0
        if wrong_form:
            score -= 45
        if matches:
            score += 10
        if specs.get("cpu"):
            score += 5
        if "DDR5" in specs.get("ram", ""):
            score += 5
        if any(token in text for token in ("thunderbolt", "usb4", "oculink")):
            score += 6
        if deal.condition == "new":
            score += 6
        elif deal.condition == "open_box":
            score += 4
        if seller_type == "classifieds":
            score -= 4

        verdict = "watch"
        if wrong_form or not matches:
            verdict = "skip"
        elif score >= 70:
            verdict = "buy"

        return DealAnalysis(
            deal=deal,
            score=max(0.0, min(100.0, score)),
            verdict=verdict,
            pros=pros,
            cons=cons,
            specs=specs,
            notes="",
            is_laptop=laptop,
            wrong_form_factor=wrong_form,
            matches_requirements=matches,
            seller_type=seller_type,
            warranty=warranty,
            domain=profile.name,
            profile=profile,
        )

    @staticmethod
    def _matches_prompt(
        prompt: str | None,
        deal: Deal,
        domain: str,
        specs: dict[str, str],
        wrong_form: bool,
    ) -> bool:
        if wrong_form:
            return False
        if not prompt:
            return True

        request = fold(prompt)
        if wants_mini_pc_form_factor(request):
            return True
        # Only apply the hardware-token gate to hardware requests. "ram" in
        # "odpruzeny ram" is a bike frame, not memory, and used to mark every
        # bicycle as not matching the request.
        if not ResultProcessor._wants_pc_details(domain, request):
            return True
        hardware_tokens = (
            "ryzen",
            "intel",
            "core i",
            "ddr",
            "ssd",
            "nvme",
            "gpu",
            "radeon",
            "thunderbolt",
            "usb4",
            "oculink",
            "ram",
        )
        listing = fold(f"{deal.title} {json.dumps(deal.metadata, ensure_ascii=False)}")
        return any(token in listing for token in hardware_tokens)

    # Words that mark a request as being about computing hardware. Used to keep
    # CPU/RAM/SSD advice out of bicycle, furniture and other non-PC reports.
    _PC_TERMS = (
        r"\b(pc|notebook|laptop|ultrabook|barebone|mini[ -]?pc|ssd|nvme|"
        r"cpu|gpu|processor|server|workstation|motherboard)\b"
    )

    @staticmethod
    def _wants_pc_details(domain: str, prompt: str | None = None) -> bool:
        """True when CPU/RAM/SSD advice is relevant to this deal."""
        if domain == "computer":
            return True
        return bool(re.search(ResultProcessor._PC_TERMS, fold(prompt or "")))

    def _heuristic_pros_cons(
        self,
        deal: Deal,
        prompt: str | None,
        specs: dict[str, str],
        seller_type: str,
        wrong_form: bool,
        laptop: bool,
        domain: str = "generic",
    ) -> tuple[list[str], list[str]]:
        text = fold(f"{deal.title} {json.dumps(deal.metadata, ensure_ascii=False)}")
        pros: list[str] = []
        cons: list[str] = []

        request = fold(prompt or "")
        if deal.metadata.get("detail_failed") or deal.metadata.get("detail_skipped"):
            cons.append(
                "listing description could not be fetched — specs may be missing"
            )
        if wrong_form:
            cons.append("Laptop/notebook form factor — not a mini PC or barebone")
        elif laptop and any(
            word in request for word in ("laptop", "notebook", "ultrabook")
        ):
            pros.append("Laptop/notebook form factor matches the request")
        elif prompt and wants_mini_pc_form_factor(prompt):
            pros.append("Matches the requested mini PC / barebone form factor")

        if self._wants_pc_details(domain, prompt):
            cpu = specs.get("cpu")
            if cpu:
                pros.append(f"Stated CPU: {cpu}")
            else:
                cons.append("Listing does not state the CPU")

            ram = specs.get("ram")
            if ram:
                if ram.startswith("No RAM"):
                    cons.append("Barebone: RAM not included — budget for SO-DIMM modules")
                elif "DDR5" in ram:
                    pros.append(f"DDR5 memory ({ram})")
                else:
                    pros.append(f"Stated memory: {ram}")
            else:
                cons.append("Listing does not state the memory size or type")

            storage = specs.get("storage")
            if storage:
                if storage.startswith("No storage"):
                    cons.append("Barebone: no SSD included — budget for an NVMe drive")
                else:
                    pros.append(f"Included storage: {storage}")

            connectivity = specs.get("connectivity")
            if connectivity:
                if any(token in connectivity.lower() for token in ("thunderbolt", "usb4", "oculink")):
                    pros.append(f"High-speed port: {connectivity}")
                else:
                    pros.append(f"Ports mentioned: {connectivity}")
            elif any(token in text for token in ("thunderbolt", "usb4", "oculink")):
                pros.append("Thunderbolt/USB4/OCuLink mentioned in the listing")

        if deal.condition == "new":
            pros.append("New item — manufacturer warranty applies")
        elif deal.condition == "open_box":
            pros.append("Open-box item — usually discounted with full warranty")
        elif deal.condition == "refurbished":
            pros.append("Refurbished — seller warranty should be confirmed")
        elif deal.condition == "used":
            cons.append("Used item — inspect and test before paying")

        if seller_type == "classifieds":
            cons.append("Private seller — no statutory warranty, verify the seller")
        elif seller_type == "retailer":
            pros.append("Sold by a retailer — returns and warranty are straightforward")

        return pros, cons

    # ------------------------------------------------------------------
    # Cross-deal scoring and alternatives
    # ------------------------------------------------------------------
    def _add_cross_alternatives(self, analyses: list[DealAnalysis]) -> None:
        relevant = [
            analysis
            for analysis in analyses
            if not analysis.wrong_form_factor and analysis.deal.price_eur > 0
        ]
        prices = [analysis.deal.price_eur for analysis in relevant]
        distinct = {round(analysis.deal.price_eur, 2) for analysis in relevant}
        median = (
            statistics.median(prices)
            if len(distinct) >= self.MIN_PRICE_SAMPLE
            else 0.0
        )

        for analysis in analyses:
            analysis.score_breakdown = self._score_breakdown(
                analysis, median, analyses
            )
            profile = analysis.profile or get(analysis.domain)
            stated = [
                key
                for key in profile.key_specs
                if (analysis.specs.get(key) or "").strip()
            ]
            analysis.spec_coverage = {
                "stated": stated,
                "missing": [key for key in profile.key_specs if key not in stated],
            }
            if analysis.wrong_form_factor:
                analysis.score = min(analysis.score, 20.0)
            else:
                # The final score must be readable from the breakdown shown
                # in the report. The model's own score is kept separately.
                analysis.score = self._weighted_score(
                    analysis.score_breakdown,
                    analysis.profile or get(analysis.domain),
                )

            if analysis.wrong_form_factor or not analysis.matches_requirements:
                analysis.verdict = "skip"
            elif analysis.score >= 70:
                analysis.verdict = "buy"
            elif analysis.score >= 45:
                analysis.verdict = "watch"
            else:
                analysis.verdict = "skip"

        # Second pass: alternative reasons quote the final scores, so they
        # must be computed after every analysis has been scored.
        for analysis in analyses:
            existing = {
                alt.get("title", "").strip().lower() for alt in analysis.alternatives
            }
            candidates = sorted(
                (
                    other
                    for other in relevant
                    if other is not analysis
                    and other.matches_requirements
                    and other.deal.price_eur < analysis.deal.price_eur
                ),
                key=lambda item: item.score,
                reverse=True,
            )
            if not candidates:
                # No fully matching cheaper deal. Still offer the best
                # alternatives from this search instead of an empty section.
                candidates = sorted(
                    (
                        other
                        for other in relevant
                        if other is not analysis
                        and (
                            other.score > analysis.score
                            or other.deal.price_eur < analysis.deal.price_eur
                        )
                    ),
                    key=lambda item: item.score,
                    reverse=True,
                )
            for other in candidates:
                if len(analysis.alternatives) >= 3:
                    break
                title_key = other.deal.title.strip().lower()
                if title_key in existing:
                    continue
                if other.deal.price_eur < analysis.deal.price_eur:
                    saving = analysis.deal.price_eur - other.deal.price_eur
                    why = (
                        f"Cheaper by {saving:.0f} EUR at {other.deal.site_name}; "
                        f"score {other.score:.0f}/100"
                    )
                else:
                    why = (
                        f"Higher-scoring option at {other.deal.site_name} "
                        f"({other.deal.price_eur:.0f} EUR); score {other.score:.0f}/100"
                    )
                if not other.matches_requirements:
                    why += " (also misses some requirements)"
                analysis.alternatives.append(
                    {
                        "title": other.deal.title,
                        "price_eur": other.deal.price_eur,
                        "why": why,
                        "source": "results",
                    }
                )
                existing.add(title_key)

    def _score_breakdown(
        self, analysis: DealAnalysis, median: float, analyses: list[DealAnalysis]
    ) -> dict[str, float]:
        deal = analysis.deal
        specs = analysis.specs
        profile = analysis.profile or get(analysis.domain)

        if analysis.wrong_form_factor:
            requirement_fit = 0.0
        elif analysis.matches_requirements:
            requirement_fit = 100.0
        else:
            requirement_fit = 15.0

        if profile.key_specs:
            stated = sum(
                1
                for key in profile.key_specs
                if (specs.get(key) or "").strip()
            )
            spec_match = float(round(100 * stated / len(profile.key_specs)))
        else:
            # An unknown product type has no vocabulary to grade against.
            spec_match = 50.0

        if median and deal.price_eur > 0:
            ratio = deal.price_eur / median
            if ratio <= 0.8:
                price_score = 95.0
            elif ratio <= 1.0:
                price_score = 75.0
            elif ratio <= 1.25:
                price_score = 55.0
            else:
                price_score = 25.0
        else:
            price_score = 50.0

        condition_score = {
            "new": 90.0,
            "open_box": 85.0,
            "refurbished": 70.0,
            "used": 50.0,
        }.get(deal.condition, 40.0)

        seller_score = {
            "retailer": 90.0,
            "marketplace": 70.0,
            "classifieds": 40.0,
            "auction": 45.0,
        }.get(analysis.seller_type, 50.0)

        if analysis.wrong_form_factor:
            spec_match = 0.0
            price_score = min(price_score, 30.0)

        rows = {
            "Requirement fit": round(requirement_fit),
            "Spec match": round(spec_match),
            "Price": round(price_score),
            "Condition & warranty": round(condition_score),
            "Seller trust": round(seller_score),
        }
        if "Connectivity" in profile.optional_rows:
            text = fold(
                f"{deal.title} {json.dumps(deal.metadata, ensure_ascii=False)}"
            )
            if any(token in text for token in ("thunderbolt", "usb4", "oculink")):
                connectivity = 90.0
            elif "2.5g" in text or "2.5 g" in text:
                connectivity = 60.0
            elif any(token in text for token in ("hdmi", "displayport", "usb-c")):
                connectivity = 40.0
            else:
                connectivity = 20.0
            rows["Connectivity"] = round(connectivity)
        return rows

    def _weighted_score(
        self, breakdown: dict[str, float], profile: DomainProfile
    ) -> float:
        """Combine a breakdown into the final score over the rows it actually has."""
        weights = dict(self.BASE_WEIGHTS)
        if "Connectivity" in profile.optional_rows:
            weights["Connectivity"] = self.CONNECTIVITY_WEIGHT
        total = sum(weights.values())
        return round(
            sum(
                breakdown.get(label, 0.0) * weight for label, weight in weights.items()
            )
            / total,
            1,
        )

    @staticmethod
    def _site_trust(deal: Deal) -> tuple[str, str]:
        """Resolve seller type and warranty note for a listing's site."""
        from src.searcher.site_registry import by_id

        spec = by_id(deal.site_name)
        if spec is not None:
            return spec.seller_type, spec.warranty_note
        return "unknown", ""

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def _deal_to_dict(
        self, analysis: DealAnalysis, rank: int, is_top_pick: bool
    ) -> dict:
        deal = analysis.deal
        price_out, currency_out = self._format_price(deal)
        return {
            "rank": rank,
            "is_top_pick": is_top_pick,
            "url": deal.url,
            "title": deal.title,
            "price_eur": deal.price_eur,
            "price": price_out,
            "currency": currency_out,
            "original_price": deal.original_price,
            "original_currency": deal.original_currency,
            "condition": deal.condition,
            "condition_label": CONDITION_LABELS.get(deal.condition, deal.condition),
            "category": deal.category,
            "site_name": deal.site_name,
            "domain": analysis.domain,
            "seller_type": analysis.seller_type,
            "warranty": analysis.warranty,
            "metadata": deal.metadata,
            "is_laptop": analysis.is_laptop,
            "wrong_form_factor": analysis.wrong_form_factor,
            "matches_requirements": analysis.matches_requirements,
            "score": analysis.score,
            "llm_score": analysis.llm_score,
            "verdict": analysis.verdict,
            "notes": analysis.notes,
            "pros": analysis.pros,
            "cons": analysis.cons,
            "specs": analysis.specs,
            "spec_coverage": analysis.spec_coverage,
            "alternatives": analysis.alternatives,
            "score_breakdown": analysis.score_breakdown,
        }

    # ------------------------------------------------------------------
    # Markdown
    # ------------------------------------------------------------------
    def _to_markdown(
        self,
        prompt: str | None,
        relevant: list[DealAnalysis],
        filtered: list[DealAnalysis],
        timestamp: str,
        top_picks: set[str],
    ) -> str:
        lines: list[str] = [f"# Deal Search Results — {timestamp}", ""]
        if prompt:
            lines += [f"**Query:** {prompt}", ""]
        lines.append(
            f"**Relevant deals:** {len(relevant)} · "
            f"**Filtered out:** {len(filtered)}"
        )
        lines.append("")

        if not relevant:
            lines.append("No deals matching the request were found.")
            if filtered:
                lines += ["", "## Filtered out", ""]
                lines += self._filtered_lines(filtered)
            return "\n".join(lines) + "\n"

        lines += ["## Summary", ""]
        lines.append(
            "| # | Pick | Product | Price | Condition | Site | Score | Verdict |"
        )
        lines.append("|---|------|---------|-------|-----------|------|-------|---------|")
        for index, analysis in enumerate(relevant, 1):
            deal = analysis.deal
            price_out, currency_out = self._format_price(deal)
            pick = "⭐" if deal.url in top_picks else ""
            verdict = VERDICT_LABELS.get(analysis.verdict, analysis.verdict)
            lines.append(
                f"| {index} | {pick} | {self._escape(deal.title)} | "
                f"{price_out:.2f} {currency_out} | "
                f"{CONDITION_LABELS.get(deal.condition, deal.condition)} | "
                f"{deal.site_name} | {analysis.score:.0f} | {verdict} |"
            )
        lines += [""]
        if relevant and all(a.verdict == "skip" for a in relevant):
            lines += [
                "**No listing fully matches the request.** The highest-scoring "
                "options and the exact gaps are listed below.",
                "",
            ]
        lines += ["---", "", "## Deal details", ""]

        for index, analysis in enumerate(relevant, 1):
            lines += self._deal_card(analysis, index, top_picks, prompt)

        if filtered:
            lines += ["## Filtered out", ""]
            lines += self._filtered_lines(filtered)

        return "\n".join(lines) + "\n"

    def _deal_card(
        self,
        analysis: DealAnalysis,
        index: int,
        top_picks: set[str],
        prompt: str | None = None,
    ) -> list[str]:
        deal = analysis.deal
        price_out, currency_out = self._format_price(deal)
        lines = [f"### {index}. {deal.title}", ""]
        lines.append(f"- **Price:** {price_out:.2f} {currency_out}")
        lines.append(
            f"- **Condition:** {CONDITION_LABELS.get(deal.condition, deal.condition)}"
        )
        lines.append(f"- **Site:** {deal.site_name}")
        profile = analysis.profile or get(analysis.domain)
        total = len(profile.key_specs)
        if total:
            stated = len(analysis.spec_coverage.get("stated", []))
            lines.append(
                f"- **Domain: {analysis.domain}** — {stated}/{total} specs stated"
            )
        else:
            lines.append(f"- **Domain: {analysis.domain}**")
        if analysis.seller_type:
            seller_label = SELLER_LABELS.get(analysis.seller_type, analysis.seller_type)
            lines.append(f"- **Seller:** {seller_label}")
        if analysis.warranty:
            lines.append(f"- **Warranty:** {analysis.warranty}")
        lines.append(f"- **Link:** [{deal.url}]({deal.url})")
        lines.append(
            f"- **Score:** {analysis.score:.0f}/100 · "
            f"**Verdict:** {VERDICT_LABELS.get(analysis.verdict, analysis.verdict)}"
            + (" · ⭐ Top pick" if deal.url in top_picks else "")
        )
        lines.append("")
        if analysis.notes:
            lines.append(f"**Assessment:** {analysis.notes}")
            lines.append("")

        if analysis.specs:
            lines.append("**Specs found in the listing:**")
            for label, value in analysis.specs.items():
                pretty_label = {
                    "cpu": "CPU",
                    "ram": "RAM",
                    "gpu": "GPU",
                    "wheel_size": "Wheel size",
                    "frame_size": "Frame size",
                    "suspension": "Suspension",
                    "brakes": "Brakes",
                    "drivetrain": "Drivetrain",
                }.get(label, label.replace("_", " ").title())
                lines.append(f"- {pretty_label}: {value}")
            lines.append("")

        if analysis.pros:
            lines.append("**✅ Pros**")
            lines += [f"- {pro}" for pro in analysis.pros]
            lines.append("")

        if analysis.cons:
            lines.append("**❌ Cons**")
            lines += [f"- {con}" for con in analysis.cons]
            lines.append("")

        if analysis.alternatives:
            lines.append("**🔄 Alternatives to consider**")
            for alt in analysis.alternatives:
                price = alt.get("price_eur")
                price_text = f"{price:.0f} €" if isinstance(price, (int, float)) else "price n/a"
                why = f" — {alt['why']}" if alt.get("why") else ""
                lines.append(f"- **{alt['title']}** ({price_text}){why}")
            lines.append("")

        if analysis.score_breakdown:
            lines.append("**📊 Score breakdown**")
            lines.append("")
            lines.append("| Criterion | Score |")
            lines.append("|-----------|-------|")
            for label, value in analysis.score_breakdown.items():
                lines.append(f"| {label} | {value:.0f}/100 |")
            lines.append("")

        lines.append("**Before you buy**")
        for item in self._checklist(deal, analysis, prompt):
            lines.append(f"- {item}")
        lines += ["", "---", ""]
        return lines

    @staticmethod
    def _checklist(
        deal: Deal, analysis: DealAnalysis, prompt: str | None = None
    ) -> list[str]:
        pc = ResultProcessor._wants_pc_details(analysis.domain, prompt)
        if deal.condition in ("new", "open_box"):
            items = [
                "Confirm the warranty length and who honours it.",
                "Check the return window and who pays return shipping.",
            ]
            if pc:
                items.append(
                    "Verify the box contains the power adapter and mounting kit."
                )
            else:
                items.append("Verify the box contains all listed accessories and parts.")
        else:
            items = [
                (
                    "Test the device before paying (boot, ports, Wi-Fi, thermals)."
                    if pc
                    else "Inspect the item in person before paying — check for "
                    "damage, wear and missing parts."
                ),
                "Ask for the purchase receipt and any remaining warranty.",
                "Check the seller's history and prefer in-person pickup.",
            ]
            if pc:
                items.append("Confirm the exact RAM and SSD configuration in person.")
                if not analysis.specs.get("ram"):
                    items.append(
                        "Ask for a screenshot of the memory configuration."
                    )
        return items

    @staticmethod
    def _filtered_lines(filtered: list[DealAnalysis]) -> list[str]:
        lines = [
            "These listings were removed because they do not match the requested "
            "form factor:",
            "",
        ]
        lines.append("| Product | Price | Site |")
        lines.append("|---------|-------|------|")
        for analysis in filtered:
            deal = analysis.deal
            lines.append(
                f"| {ResultProcessor._escape(deal.title)} | "
                f"{deal.price_eur:.0f} € | {deal.site_name} |"
            )
        lines.append("")
        return lines

    @staticmethod
    def _escape(text: str) -> str:
        return (text or "").replace("|", "\\|")
