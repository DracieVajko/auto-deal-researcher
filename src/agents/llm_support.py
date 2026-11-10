"""Shared LLM plumbing for Diamond Search agents.

Agents must keep working when no LLM is reachable (local model still loading,
all providers down). Every helper here degrades to ``None`` instead of
raising, so each agent can fall back to its deterministic heuristic.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


class LLMBackedAgent:
    """Mixin giving an agent optional access to the shared LLMClient."""

    def __init__(self, llm=None, name: str = "", role: str = "") -> None:
        self.llm = llm
        if name:
            self.name = name
        if role:
            self.role = role

    async def _ask(self, system: str, user: str, max_tokens: int = 400) -> str | None:
        """One LLM round-trip. Returns None when no LLM is available/failed."""
        if self.llm is None:
            return None
        try:
            chat = getattr(self.llm, "chat", None)
            if chat is None:
                return None
            result = chat(system, user, max_tokens)
            if hasattr(result, "__await__"):
                result = await result
            text = (result or "").strip()
            return text or None
        except Exception as e:  # noqa: BLE001 - agents must never hard-fail
            logger.warning(f"[{self.name}] LLM call failed: {type(e).__name__}: {e}")
            return None

    async def _ask_json(self, system: str, user: str, max_tokens: int = 400, default=None):
        """Ask for JSON and parse it, tolerating markdown fences and prose."""
        raw = await self._ask(system, user, max_tokens)
        if not raw:
            return default
        parsed = extract_json(raw)
        return parsed if parsed is not None else default


def extract_json(raw: str):
    """Best-effort JSON extraction from an LLM reply.

    Thinking models (Qwen 3, Nemotron, ...) emit a long reasoning trace
    before the answer.  The answer is almost always the *last* JSON value in
    the reply, but it may contain nested objects/arrays (a quote list inside a
    wrapper object).  Collect balanced values, drop the ones nested inside
    another, and try the outermost values from last to first.
    """
    if not raw:
        return None
    text = raw.strip()

    # Fenced blocks: the last fence is the most likely answer.
    fences = re.findall(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    for block in reversed(fences):
        try:
            return json.loads(block.strip())
        except (ValueError, TypeError):
            continue

    # Many models answer with bare JSON, possibly with surrounding whitespace.
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    # Balanced scan that ignores braces/brackets inside JSON strings.
    candidates: list[tuple[int, int]] = []
    for start, opener in enumerate(text):
        if opener not in "{[":
            continue
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidates.append((start, i))
                    break

    # Keep only outermost candidates; nested blocks are part of their parent.
    outermost = [
        (start, end)
        for start, end in candidates
        if not any(s <= start and end <= e and (s, e) != (start, end) for s, e in candidates)
    ]
    for start, end in reversed(outermost):
        try:
            return json.loads(text[start : end + 1])
        except (ValueError, TypeError):
            continue
    return None


def as_list(value, limit: int) -> list[str]:
    """Coerce an LLM reply into a clean, de-duplicated list of strings."""
    items: list[str] = []
    if isinstance(value, str):
        candidates = re.split(r"[\n;]", value)
    elif isinstance(value, list):
        candidates = value
    else:
        return items

    for c in candidates:
        if isinstance(c, dict):
            c = c.get("query") or c.get("title") or c.get("name") or ""
        if not isinstance(c, str):
            continue
        # Strip list bullets, quotes and brackets from either end.
        c = re.sub(r'^[\s\-*"\'\[\]()]+|[\s\-*"\'\[\]()]+$', "", c)
        c = " ".join(c.split())
        if 2 < len(c) <= 120 and c not in items:
            items.append(c)
    return items[:limit]