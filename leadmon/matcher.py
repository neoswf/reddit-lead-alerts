"""Decides whether a post matches a client, and says why in plain words."""
import re
from dataclasses import dataclass, field

_patterns = {}


@dataclass
class MatchResult:
    matched: bool
    reason: str
    excluded_by: list = field(default_factory=list)


def _pattern(phrase: str) -> re.Pattern:
    """Case-insensitive and whole words only, so "seo" does not fire inside "seoul"."""
    if phrase not in _patterns:
        words = phrase.lower().split()
        body = r"\s+".join(re.escape(w) for w in words)
        start = r"(?<!\w)" if re.match(r"\w", words[0]) else ""
        end = r"(?!\w)" if re.search(r"\w$", words[-1]) else ""
        _patterns[phrase] = re.compile(start + body + end, re.IGNORECASE)
    return _patterns[phrase]


def _hits(phrases: list, title: str, text: str) -> list:
    hits = []
    for phrase in phrases:
        pattern = _pattern(phrase)
        where = [label for label, s in (("title", title), ("post", text)) if pattern.search(s)]
        if where:
            hits.append((phrase, where))
    return hits


def _describe(hits: list) -> str:
    return ", ".join(f'"{phrase}" in {" and ".join(where)}' for phrase, where in hits)


def match(item, client) -> MatchResult:
    excluded = _hits(client.exclude, item.title, item.text)
    if excluded:
        return MatchResult(False, "excluded: " + _describe(excluded), [p for p, _ in excluded])

    included = _hits(client.include, item.title, item.text)
    if not included:
        return MatchResult(False, "no include phrase")

    location = _hits(client.location_terms, item.title, item.text)
    if client.location_required and not location:
        return MatchResult(False, "matched " + _describe(included) + ", but no location term")

    reason = "matched " + _describe(included)
    if location:
        reason += "; location " + _describe(location)
    return MatchResult(True, reason)
