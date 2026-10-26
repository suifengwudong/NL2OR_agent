"""Global keyword-based search utilities shared by all tools.

All search functions operate on plain dict/list data — they don't know about
files or paths.  Each tool loads its own data and hands it to these helpers.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Keyword parsing
# ---------------------------------------------------------------------------


def parse_keywords(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize keyword input into a list of lower-case trimmed tokens."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(kw).strip().lower() for kw in raw if str(kw).strip()]
    text = str(raw).strip()
    if not text:
        return []
    return [kw.strip().lower() for kw in text.split(",") if kw.strip()]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_keywords(keywords: list[str], haystack: list[str]) -> int:
    """Return the number of *keywords* that appear (as substring) in *haystack*."""
    haystack_lower = [h.lower() for h in haystack]
    score = 0
    for kw in keywords:
        for h in haystack_lower:
            if kw in h or h in kw:
                score += 1
                break
    return score


# ---------------------------------------------------------------------------
# Search over dictionaries / lists
# ---------------------------------------------------------------------------


def search_by_keywords(
    items: list[dict[str, Any]],
    keywords: list[str],
    *,
    search_fields: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Generic keyword search over a list of dicts.

    Parameters
    ----------
    items:
        List of dict items to search.
    keywords:
        Normalized keyword tokens (see ``parse_keywords``).
    search_fields:
        Which dict keys to look in.  ``None`` means all ``str`` values.
    limit:
        Max results to return (sorted by score descending).
    """
    if not keywords:
        return []

    scored: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        values = (
            [item.get(field) for field in search_fields]
            if search_fields is not None
            else list(item.values())
        )
        haystack: list[str] = []
        for value in values:
            if isinstance(value, list):
                haystack.extend(str(entry) for entry in value)
            elif value is not None:
                haystack.append(str(value))

        s = score_keywords(keywords, haystack)
        if s > 0:
            scored.append((s, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]
