"""Hallucination guard: verify that every quote the model cites actually appears in the source text."""

import re
from difflib import SequenceMatcher
from typing import Any

from app.schemas import DocumentInsights

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    s = s.lower().replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    return _WS.sub(" ", s).strip()


def quote_is_grounded(quote: str, text_norm: str, threshold: float = 0.88) -> bool:
    q = _norm(quote).strip(" .\"'")
    if not q:
        return False
    if q in text_norm:
        return True
    # Tolerate small differences (whitespace from PDF extraction, punctuation): fuzzy-match the
    # quote against windows around occurrences of its first few words.
    anchor = q[: min(24, len(q))]
    start = text_norm.find(anchor)
    while start != -1:
        window = text_norm[start : start + len(q) + 40]
        if SequenceMatcher(None, q, window[: len(q)]).ratio() >= threshold:
            return True
        start = text_norm.find(anchor, start + 1)
    return False


def check_grounding(insights: DocumentInsights, text: str) -> dict[str, Any]:
    text_norm = _norm(text)
    items: list[dict[str, Any]] = []
    # An empty quote is legitimate for things that are *missing* (e.g. "no data-protection terms"):
    # there is nothing to verify, so it is neither counted as grounded nor as a hallucination.
    for i, d in enumerate(insights.key_dates):
        if d.source_quote.strip():
            items.append({"kind": "date", "index": i, "grounded": quote_is_grounded(d.source_quote, text_norm)})
    for i, r in enumerate(insights.risks):
        if r.source_quote.strip():
            items.append({"kind": "risk", "index": i, "grounded": quote_is_grounded(r.source_quote, text_norm)})
    grounded = sum(1 for it in items if it["grounded"])
    return {
        "checked": len(items),
        "grounded": grounded,
        "ungrounded": len(items) - grounded,
        "score": round(grounded / len(items), 3) if items else 1.0,
        "items": items,
    }
