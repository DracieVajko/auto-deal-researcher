"""LLM benchmark for the Auto Deal Searcher's real jobs.

Runs the app's own methods against a local LM Studio model and validates the
answers with the same rules the pipeline uses. Developer tool, not part of the
test suite.

Usage:
    python scripts/llm_bench.py --model nvidia-nemotron-3.5-bolt-e4b
    python scripts/llm_bench.py --model M --ids judge_01_sk,classify_01_sk
    python scripts/llm_bench.py --model M --no-reasoning
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from src.agents.research.query_expansion import QueryExpansionAgent  # noqa: E402
from src.config.models import AppConfig, LLMConfig, LLMLocalConfig  # noqa: E402
from src.llm.client import LLMClient  # noqa: E402
from src.output.domains.ai import propose_domain  # noqa: E402
from src.searcher.adapters.base import Deal  # noqa: E402
from src.searcher.query_language import localise_query  # noqa: E402
from src.text.normalize import fold  # noqa: E402

ENDPOINT = "http://localhost:1234"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _fold(value: Any) -> str:
    return fold(str(value or ""))


def _contains(value: Any, token: str) -> bool:
    return token.lower() in _fold(value)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_extract(data: Any, expect: dict) -> list[str]:
    if not isinstance(data, dict):
        return [f"not a dict: {data!r}"]
    reasons: list[str] = []
    for key in ("min_price", "max_price"):
        value = data.get(key)
        if value is not None and not _is_number(value):
            reasons.append(f"{key} is not numeric: {value!r}")
    if "condition" in expect and _fold(data.get("condition")) != expect["condition"]:
        reasons.append(f"condition={data.get('condition')!r}, expected {expect['condition']!r}")
    if "category" in expect:
        allowed = expect["category"] if isinstance(expect["category"], list) else [expect["category"]]
        if _fold(data.get("category")) not in {_fold(a) for a in allowed}:
            reasons.append(f"category={data.get('category')!r}, expected {allowed!r}")
    if "brand" in expect and not _contains(data.get("brand"), expect["brand"]):
        reasons.append(f"brand={data.get('brand')!r}, expected {expect['brand']!r}")
    if "location" in expect and not _contains(data.get("location"), expect["location"]):
        reasons.append(f"location={data.get('location')!r}, expected {expect['location']!r}")
    if "max_price" in expect:
        got = data.get("max_price")
        if not _is_number(got) or abs(float(got) - float(expect["max_price"])) > 0.01:
            reasons.append(f"max_price={got!r}, expected {expect['max_price']}")
    if "min_price" in expect:
        got = data.get("min_price")
        if not _is_number(got) or abs(float(got) - float(expect["min_price"])) > 0.01:
            reasons.append(f"min_price={got!r}, expected {expect['min_price']}")
    if expect.get("max_price_null") and data.get("max_price") is not None:
        reasons.append(f"hallucinated max_price={data.get('max_price')!r}")
    if expect.get("min_price_null") and data.get("min_price") is not None:
        reasons.append(f"hallucinated min_price={data.get('min_price')!r}")
    for forbidden in expect.get("forbidden_max_price", []):
        got = data.get("max_price")
        if _is_number(got) and abs(float(got) - float(forbidden)) <= 0.01:
            reasons.append(f"max_price took a non-price number {forbidden}")
    extras = data.get("extras")
    if extras is not None and not isinstance(extras, dict):
        reasons.append(f"extras is not an object: {type(extras).__name__}")
    elif expect.get("extras_contains"):
        flat = _fold(json.dumps(extras or {}, ensure_ascii=False))
        for token in expect["extras_contains"]:
            if token.lower() not in flat:
                reasons.append(f"extras missing {token!r}: {extras!r}")
    return reasons


def validate_classify(result: Any, expected: dict[str, dict]) -> list[str]:
    if not isinstance(result, dict):
        return [f"not a dict: {result!r}"]
    reasons: list[str] = []
    for card_id, fields in expected.items():
        payload = result.get(card_id)
        if not isinstance(payload, dict):
            reasons.append(f"missing card {card_id}")
            continue
        for key, want in fields.items():
            got = payload.get(key)
            if isinstance(want, float) and _is_number(got):
                if abs(float(got) - want) > 0.01:
                    reasons.append(f"{card_id}.{key}={got!r}, expected {want!r}")
            elif got != want:
                reasons.append(f"{card_id}.{key}={got!r}, expected {want!r}")
    return reasons


def validate_judge(value: Any, expected_keep: set[str]) -> list[str]:
    if not isinstance(value, dict) or "keep" not in value:
        return [f"not a dict with 'keep': {value!r}"]
    keep = {str(url) for url in value.get("keep") or []}
    reasons: list[str] = []
    if missing := expected_keep - keep:
        reasons.append(f"missing KEEP: {sorted(missing)}")
    if extra := keep - expected_keep:
        reasons.append(f"unexpected KEEP: {sorted(extra)}")
    return reasons


def validate_query(value: Any, tokens: list[str], max_words: int = 6) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return ["empty query"]
    query = value.strip()
    reasons: list[str] = []
    if len(query.split()) > max_words:
        reasons.append(f"too many words ({len(query.split())}): {query!r}")
    if tokens and not any(_contains(query, token) for token in tokens):
        reasons.append(f"query {query!r} lacks any of {tokens}")
    return reasons


def validate_translate(value: Any, query: str, required: list[str],
                       any_of: list[str], must_change: bool | None = None) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return ["empty translation"]
    if must_change is None:
        # Product/model names are already correct in every language; only
        # require a visible change when the test expects target-language words.
        must_change = bool(any_of)
    reasons: list[str] = []
    if must_change and value.strip().lower() == query.strip().lower():
        reasons.append("query was not translated")
    for token in required:
        if token not in value:
            reasons.append(f"lost protected token {token!r}: {value!r}")
    if any_of and not any(_contains(value, token) for token in any_of):
        reasons.append(f"translation {value!r} lacks any of {any_of}")
    return reasons


def validate_refine(value: Any, prompt: str) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return ["empty refined query"]
    reasons: list[str] = []
    if value.strip().lower() == prompt.strip().lower():
        reasons.append("refined query is identical to the original")
    if len(value.split()) > 6:
        reasons.append(f"too many words ({len(value.split())}): {value!r}")
    return reasons


def validate_rank(value: Any, deals: list[Deal], expected_top: str) -> list[str]:
    if not isinstance(value, list):
        return [f"not a list: {type(value).__name__}"]
    urls = [deal.url for deal in value]
    reasons: list[str] = []
    if len(urls) != len(deals):
        reasons.append(f"returned {len(urls)} deals, expected {len(deals)}")
    if len(set(urls)) != len(urls):
        reasons.append("duplicate deals in ranking")
    if set(urls) != {deal.url for deal in deals}:
        reasons.append("ranking is not a permutation of the input deals")
    if urls and urls[0] != expected_top:
        reasons.append(f"top deal is {urls[0]!r}, expected {expected_top!r}")
    return reasons


def validate_specs(data: Any, expect: dict) -> list[str]:
    if not isinstance(data, dict):
        return [f"not a dict: {data!r}"]
    reasons: list[str] = []
    if "brand" in expect and not _contains(data.get("brand"), expect["brand"]):
        reasons.append(f"brand={data.get('brand')!r}, expected {expect['brand']!r}")
    if "model" in expect and not _contains(data.get("model"), expect["model"]):
        reasons.append(f"model={data.get('model')!r}, expected {expect['model']!r}")
    if "price" in expect:
        got = data.get("price_eur")
        if not _is_number(got) or abs(float(got) - float(expect["price"])) > 0.01:
            reasons.append(f"price_eur={got!r}, expected {expect['price']}")
    if expect.get("price_null") and data.get("price_eur") is not None:
        reasons.append(f"hallucinated price_eur={data.get('price_eur')!r}")
    if expect.get("extras_contains"):
        flat = _fold(json.dumps(data.get("extras") or {}, ensure_ascii=False))
        for token in expect["extras_contains"]:
            if token.lower() not in flat:
                reasons.append(f"extras missing {token!r}: {data.get('extras')!r}")
    return reasons


def validate_reviews(data: Any, forbidden: list[str]) -> list[str]:
    if not isinstance(data, dict):
        return [f"not a dict: {data!r}"]
    reasons: list[str] = []
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        reasons.append("missing summary")
    for key in ("pros", "cons"):
        if not isinstance(data.get(key), list):
            reasons.append(f"{key} is not a list")
    flat = _fold(json.dumps(data, ensure_ascii=False))
    for token in forbidden:
        if token.lower() in flat:
            reasons.append(f"forbidden token {token!r} in review")
    return reasons


def validate_expand(value: Any, tokens: list[str], minimum: int = 3) -> list[str]:
    if not isinstance(value, dict):
        return [f"not a dict: {value!r}"]
    queries = value.get("expanded_queries")
    if not isinstance(queries, list) or len(queries) < minimum:
        return [f"expected >= {minimum} queries, got {queries!r}"]
    reasons: list[str] = []
    joined = " ".join(str(q) for q in queries)
    if tokens and not any(_contains(joined, token) for token in tokens):
        reasons.append(f"expanded queries lack any of {tokens}")
    return reasons


def validate_domain(value: Any) -> list[str]:
    if value is None:
        return ["proposal rejected (None)"]
    reasons: list[str] = []
    if not getattr(value, "domain", ""):
        reasons.append("missing domain")
    if len(getattr(value, "key_specs", [])) < 2:
        reasons.append(f"too few key_specs: {getattr(value, 'key_specs', None)!r}")
    if not getattr(value, "keywords", []):
        reasons.append("missing keywords")
    return reasons


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

@dataclass
class Case:
    id: str
    job: str
    language: str
    run: Callable[[LLMClient], Awaitable[Any]]
    validate: Callable[[Any], list[str]]
    note: str = ""


def _extract_case(case_id, language, prompt, expect):
    return Case(case_id, "extract_search_filters", language,
                lambda c: c.extract_search_filters(prompt),
                lambda v: validate_extract(v, expect), prompt)


def _query_case(case_id, language, prompt, tokens):
    return Case(case_id, "generate_search_query", language,
                lambda c: c.generate_search_query_async(prompt),
                lambda v: validate_query(v, tokens), prompt)


def _translate_case(case_id, language, query, target, required, any_of):
    return Case(case_id, "localise_query", language,
                lambda c: localise_query(c, query, target, {}),
                lambda v: validate_translate(v, query, required, any_of),
                f"{query} -> {target}")


def _refine_case(case_id, language, prompt, found):
    deals = [Deal(url=f"f{i}", title=t, price_eur=100.0 + i, condition="used", site_name="bazos")
             for i, t in enumerate(found)]
    return Case(case_id, "refine_query", language,
                lambda c: c.refine_query(prompt, deals, 1),
                lambda v: validate_refine(v, prompt), prompt)


def _judge_case(case_id, language, prompt, deals, expected):
    return Case(case_id, "judge_results", language,
                lambda c: c.judge_results(prompt, deals),
                lambda v: validate_judge(v, expected), prompt)


def _rank_case(case_id, language, prompt, deals, top):
    return Case(case_id, "rank_results", language,
                lambda c: c.rank_results(prompt, deals, top_n=len(deals)),
                lambda v: validate_rank(v, deals, top), prompt)


def _classify_case(case_id, language, cards, expected):
    return Case(case_id, "classify_price_quotes", language,
                lambda c: c.classify_price_quotes(cards),
                lambda v: validate_classify(v, expected), f"{len(cards)} cards")


SPECS_SYSTEM = (
    "You extract structured product specifications from web search snippets. "
    "Return ONLY a JSON object with keys: category, condition, brand, model, "
    "year, price_eur, power_kw, power_hp, weight_kg, length_mm, width_mm, "
    "height_mm, battery_kwh, range_km, extras. Use null for unknown values. "
    "Prices are EUR. Power in kW (convert hp if needed). Weight in kg. "
    "Dimensions in mm. Battery in kWh (EVs only). Range in km. ``extras`` is "
    "an object of string key/value pairs for anything else (voltage_volt, "
    "wheel_size_inch, storage_gb, etc.). Do not invent values."
)


def _specs_case(case_id, language, item, snippets, expect):
    user = (f"Item: {item}\nCategory: electronics\n"
            f"Search snippets: {snippets[:4000]}\nExtract the specs.")
    return Case(case_id, "chat_json_specs", language,
                lambda c: c.chat_json(SPECS_SYSTEM, user, max_tokens=600),
                lambda v: validate_specs(v, expect), item)


def _reviews_case(case_id, language, item, snippets, forbidden):
    system = ("You summarise product reviews from web snippets. Return ONLY a "
              "JSON object with keys: summary (1-2 sentences), pros (list of "
              "strings), cons (list of strings). Keep each pro/con short. Use "
              "empty lists if none found. Do not invent claims.")
    user = f"Item: {item}\nSearch snippets: {snippets[:3000]}\nSummarise the reviews."
    return Case(case_id, "chat_json_reviews", language,
                lambda c: c.chat_json(system, user, max_tokens=400),
                lambda v: validate_reviews(v, forbidden), item)


def _expansion_case(case_id, language, prompt, tokens):
    async def run(c):
        return await QueryExpansionAgent(c).run({"prompt": prompt, "max_queries": 8})
    return Case(case_id, "query_expansion", language, run,
                lambda v: validate_expand(v, tokens), prompt)


def _domain_case(case_id, language, listing, prompt):
    return Case(case_id, "propose_domain", language,
                lambda c: propose_domain(c, listing, prompt),
                validate_domain, prompt)


def mini_pc_deals():
    return [
        Deal(url="d1", title="Mini PC Beelink SER5 Ryzen 7 5800H 32GB RAM 500GB SSD", price_eur=450, condition="new", site_name="Alza"),
        Deal(url="d2", title="Laptop Lenovo ThinkPad T14 32GB RAM 1TB", price_eur=480, condition="used", site_name="Bazos"),
        Deal(url="d3", title="Gaming PC desktop Ryzen 7 32GB RAM RTX 3060", price_eur=700, condition="new", site_name="Alza"),
        Deal(url="d4", title="Mini PC barebone NUC 32GB RAM", price_eur=420, condition="used", site_name="Bazos"),
        Deal(url="d5", title="RAM DDR4 32GB kit 3200MHz", price_eur=80, condition="new", site_name="Alza"),
        Deal(url="d6", title="Mini PC Intel N100 8GB RAM 256GB", price_eur=180, condition="new", site_name="Alza"),
        Deal(url="d7", title="Mini PC Beelink 32GB RAM", price_eur=520, condition="new", site_name="Alza"),
        Deal(url="d8", title="Mini PC ASUS PN50 Ryzen 5 32GB RAM", price_eur=499, condition="used", site_name="Bazos"),
        Deal(url="d9", title="Mini PC case only ITX", price_eur=40, condition="new", site_name="Alza"),
        Deal(url="d10", title="Mini PC HP EliteDesk 800 G4 i5 32GB RAM", price_eur=350, condition="used", site_name="Bazos"),
    ]


def book_deals():
    return [
        Deal(url="b1", title="PocketBook 634Verse Pro 299 EUR", price_eur=299, condition="new", site_name="Alza"),
        Deal(url="b2", title="PocketBook 634Verse Pro 349 EUR", price_eur=349, condition="used", site_name="Bazos"),
        Deal(url="b3", title="PocketBook 634 250 EUR", price_eur=250, condition="new", site_name="Bazos"),
        Deal(url="b4", title="PocketBook 634Verse Pro obal/cover 20 EUR", price_eur=20, condition="new", site_name="Alza"),
        Deal(url="b5", title="PocketBook 634Verse Pro 280 EUR", price_eur=280, condition="refurbished", site_name="Bazos"),
        Deal(url="b6", title="PocketBook 634Verse Pro 310 EUR", price_eur=310, condition="new", site_name="Alza"),
        Deal(url="b7", title="PocketBook 634Verse Pro 295 EUR", price_eur=295, condition="new", site_name="Alza"),
    ]


def iphone_deals():
    return [
        Deal(url="r1", title="iPhone 15 Pro 256GB", price_eur=600, condition="used", site_name="Bazos"),
        Deal(url="r2", title="iPhone 15 128GB", price_eur=450, condition="used", site_name="Bazos"),
        Deal(url="r3", title="iPhone 15 256GB", price_eur=520, condition="used", site_name="Alza"),
        Deal(url="r4", title="iPhone 14 128GB", price_eur=380, condition="used", site_name="Bazos"),
    ]


def price_cards():
    return [
        {"id": "p1", "text": "PocketBook 634Verse Pro 299 € Doprava zdarma", "listed_price_eur": 299.0, "currency": "EUR"},
        {"id": "p2", "text": "PocketBook 634Verse Pro 289 € + 9,90 € doprava", "listed_price_eur": 289.0, "currency": "EUR"},
        {"id": "p3", "text": "PocketBook 634Verse Pro 249 € s kódom SALE20", "listed_price_eur": 249.0, "currency": "EUR"},
        {"id": "p4", "text": "PocketBook 634Verse Pro 279 € len pre nových zákazníkov", "listed_price_eur": 279.0, "currency": "EUR"},
        {"id": "p5", "text": "PocketBook 634Verse Pro od 259 €", "listed_price_eur": 259.0, "currency": "EUR"},
        {"id": "p6", "text": "Obal na PocketBook 634Verse Pro 2 ks za 19,90 €", "listed_price_eur": 19.9, "currency": "EUR"},
    ]


def build_cases():
    cases: list[Case] = []
    extract_specs = [
        ("sk", "PocketBook 634Verse Pro pod 300 eur, nový, Bratislava", {"max_price": 300, "condition": "new", "category": "electronics", "brand": "pocketbook", "location": "bratislava"}),
        ("cs", "hledám levný telefon do 200 eur, použitý, Praha", {"max_price": 200, "condition": "used", "category": "electronics", "location": "praha"}),
        ("en", "used DJI Mini 3 Pro drone under 400 EUR", {"max_price": 400, "condition": "used", "category": ["electronics", "hobby"], "brand": "dji"}),
        ("de", "gebrauchtes iPhone 15 Pro bis 600 Euro, München", {"max_price": 600, "condition": "used", "category": "electronics", "brand": "iphone", "location": "munchen"}),
        ("pl", "używany rower górski do 500 euro, Kraków", {"max_price": 500, "condition": "used", "category": "hobby", "location": "krakow"}),
        ("hu", "használt laptop 300 euró alatt, Budapest", {"max_price": 300, "condition": "used", "category": "electronics", "location": "budapest"}),
        ("multi", "Hľadám čierny PocketBook 634Verse Pro", {"max_price_null": True, "min_price_null": True, "brand": "pocketbook"}),
        ("multi", "24V elektrická kolobežka 500W, 10 inch kolesá, do 400 eur", {"max_price": 400, "forbidden_max_price": [24, 500, 10], "category": "hobby"}),
        ("multi", "iPhone 15 128GB pod 500 eur", {"max_price": 500, "forbidden_max_price": [128], "category": "electronics", "brand": "iphone", "extras_contains": ["128"]}),
        ("multi", "dron od 200 do 500 eur", {"min_price": 200, "max_price": 500, "category": ["electronics", "hobby"]}),
    ]
    for i, (lang, prompt, expect) in enumerate(extract_specs, 1):
        cases.append(_extract_case(f"extract_{i:02d}_{lang}", lang, prompt, expect))

    cases.append(_classify_case("classify_01_sk", "sk", price_cards(), {
        "p1": {"kind": "regular", "shipping_is_free": True},
        "p2": {"kind": "regular", "shipping_cost_eur": 9.9},
        "p3": {"kind": "coupon"},
        "p4": {"kind": "account_gated"},
        "p5": {"kind": "range", "price_from": True},
        "p6": {"kind": "bundle", "bundle_min_quantity": 2},
    }))

    cases.append(_judge_case("judge_01_sk", "sk", "mini PC s 32GB RAM do 500 eur", mini_pc_deals(), {"d1", "d4", "d8", "d10"}))
    cases.append(_judge_case("judge_02_sk", "sk", "PocketBook 634Verse Pro pod 300 eur, nový", book_deals(), {"b1", "b7"}))

    query_specs = [
        ("sk", "PocketBook 634Verse Pro pod 300 eur, nový, Bratislava", ["pocketbook", "634"]),
        ("cs", "hledám levný telefon do 200 eur, použitý, Praha", ["telefon", "phone", "mobil"]),
        ("en", "used DJI Mini 3 Pro drone under 400 EUR", ["dji", "drone", "mini"]),
        ("de", "gebrauchtes iPhone 15 Pro bis 600 Euro, München", ["iphone", "15"]),
        ("pl", "używany rower górski do 500 euro, Kraków", ["rower", "bike", "gorski"]),
        ("hu", "használt laptop 300 euró alatt, Budapest", ["laptop", "notebook"]),
    ]
    for i, (lang, prompt, tokens) in enumerate(query_specs, 1):
        cases.append(_query_case(f"query_{i:02d}_{lang}", lang, prompt, tokens))

    translate_specs = [
        ("sk", "predam horsky bicykel", "de", [], ["fahrrad", "bike", "fahrrader"]),
        ("en", "iPhone 15 Pro Max", "de", ["iPhone", "15", "Pro", "Max"], []),
        ("en", "PocketBook 634Verse Pro", "cs", ["PocketBook", "634Verse", "Pro"], []),
        ("sk", "bezdrôtová klávesnica", "en", [], ["keyboard", "wireless"]),
        ("sk", "slúchadlá Sony WH-1000XM5", "de", ["Sony", "WH-1000XM5"], []),
    ]
    for i, (lang, query, target, required, any_of) in enumerate(translate_specs, 1):
        cases.append(_translate_case(f"translate_{i:02d}_{lang}_{target}", lang, query, target, required, any_of))

    refine_specs = [
        ("sk", "mini PC 32GB RAM do 500 eur", ["Mini PC Beelink SER5 32GB RAM 500GB", "Mini PC ASUS PN50 Ryzen 5 32GB", "Mini PC Intel NUC 32GB RAM"]),
        ("en", "PocketBook 634Verse Pro under 300 EUR", ["PocketBook 634Verse Pro 299 EUR", "PocketBook 634 250 EUR"]),
    ]
    for i, (lang, prompt, found) in enumerate(refine_specs, 1):
        cases.append(_refine_case(f"refine_{i:02d}_{lang}", lang, prompt, found))

    cases.append(_rank_case("rank_01_sk", "sk", "najlacnejší iPhone 15 128GB", iphone_deals(), "r2"))
    cases.append(_rank_case("rank_02_de", "de", "günstigstes iPhone 15 128GB", iphone_deals(), "r2"))

    cases.append(_specs_case("specs_01_sk", "sk", "PocketBook 634Verse Pro",
                             "PocketBook 634Verse Pro má 7-palcový E Ink displej, 32 GB úložisko, batériu 2100 mAh, hmotnosť 228 g, IPX8. Cena 299 €.",
                             {"brand": "pocketbook", "model": "634verse", "price": 299, "extras_contains": ["32"]}))
    cases.append(_specs_case("specs_02_sk", "sk", "Xiaomi 14",
                             "Xiaomi 14 má 6,36-palcový AMOLED displej, Snapdragon 8 Gen 3, 12 GB RAM, 256 GB úložisko, batériu 4610 mAh.",
                             {"brand": "xiaomi", "model": "14", "price_null": True}))

    cases.append(_reviews_case("reviews_01_sk", "sk", "PocketBook 634Verse Pro",
                               "Recenzia PocketBook 634Verse Pro: chvália 7-palcový E Ink displej, výdrž batérie a IPX8. Kritizujú pomalé rozhranie a vyššiu cenu.",
                               ["iphone", "kindle"]))

    cases.append(_expansion_case("expand_01_sk", "sk", "PocketBook 634Verse Pro pod 300 eur", ["pocketbook", "634"]))
    cases.append(_expansion_case("expand_02_de", "de", "gebrauchtes iPhone 15 Pro unter 600 Euro", ["iphone", "15"]))

    listing = "Elektrická jednokolka Inmotion V11 1500W, batéria 84V 960Wh, dojazd 100 km, hmotnosť 27 kg, cena 1200 €."
    cases.append(_domain_case("domain_01_sk", "sk", listing, "hľadám elektrickú jednokolku do 1500 eur"))
    return cases


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def build_client(model, timeout, reasoning=True):
    os.environ["ADS_LOCAL_LLM_TIMEOUT"] = str(timeout)
    os.environ["ADS_LOCAL_BREAKER_THRESHOLD"] = "999"
    os.environ["ADS_LOCAL_BREAKER_COOLDOWN"] = "0"
    config = AppConfig()
    config.llm = LLMConfig(
        local=[LLMLocalConfig(type="lmstudio", endpoint=ENDPOINT, model=model)],
        api_fallback=[],
        reasoning_enabled=reasoning,
    )
    client = LLMClient(config)
    client._monitor = None
    client._coordinator = None
    return client


async def run_case(client, case, timeout):
    client._breaker.reset()
    started = time.perf_counter()
    error = None
    value = None
    try:
        value = await asyncio.wait_for(case.run(client), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    reasons = [f"EXCEPTION: {error}"] if error else case.validate(value)
    return {"id": case.id, "job": case.job, "language": case.language,
            "note": case.note, "passed": not reasons, "reasons": reasons,
            "elapsed": round(elapsed, 3), "error": error,
            "value_preview": str(value)[:600]}


async def run_model(model, cases, timeout, reasoning):
    client = build_client(model, timeout, reasoning)
    results = []
    for i, case in enumerate(cases, 1):
        result = await run_case(client, case, timeout)
        result["model"] = model
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"[{i:02d}/{len(cases):02d}] {model} :: {case.id} {status} {result['elapsed']:.1f}s")
        for reason in result["reasons"]:
            print(f"         - {reason}")
        if result["error"]:
            print(f"         ! {result['error']}")
    return results


def summarize(results):
    models = {}
    for result in results:
        models.setdefault(result["model"], []).append(result)
    lines = ["| Model | Cases | Pass | Avg s | p50 s |", "|---|---|---|---|---|"]
    for model, rows in models.items():
        passed = sum(1 for row in rows if row["passed"])
        latencies = sorted(row["elapsed"] for row in rows)
        lines.append(f"| {model} | {len(rows)} | {passed}/{len(rows)} | "
                     f"{sum(latencies)/len(latencies):.1f} | {latencies[len(latencies)//2]:.1f} |")
    lines += ["", "### Per job", "", "| Job | Pass | Avg s | Notes |", "|---|---|---|---|"]
    jobs = {}
    for result in results:
        jobs.setdefault(result["job"], []).append(result)
    for job, rows in jobs.items():
        passed = sum(1 for row in rows if row["passed"])
        avg = sum(row["elapsed"] for row in rows) / len(rows)
        failed = [row for row in rows if not row["passed"]]
        note = "; ".join(f"{row['id']}: {row['reasons'][0]}" for row in failed[:3])
        lines.append(f"| {job} | {passed}/{len(rows)} | {avg:.1f} | {note} |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--ids", default="")
    parser.add_argument("--jobs", default="")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--out", default="llm_bench_results.json")
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--no-reasoning", action="store_true")
    args = parser.parse_args(argv)

    load_dotenv(".env")
    cases = build_cases()
    ids = {item.strip() for item in args.ids.split(",") if item.strip()}
    jobs = {item.strip() for item in args.jobs.split(",") if item.strip()}
    if ids:
        cases = [c for c in cases if c.id in ids]
    if jobs:
        cases = [c for c in cases if c.job in jobs]
    if not cases:
        print("No cases matched.")
        return 2
    if args.list_cases:
        for case in cases:
            print(f"{case.id:28s} {case.job:24s} {case.language}")
        return 0

    all_results = []
    for model in args.model:
        print(f"\n=== {model} ({len(cases)} cases) ===")
        all_results.extend(asyncio.run(
            run_model(model, cases, args.timeout, not args.no_reasoning)
        ))
    report = summarize(all_results)
    print("\n" + report)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
    output.with_suffix(".md").write_text(report + "\n", encoding="utf-8")
    print(f"\nSaved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
