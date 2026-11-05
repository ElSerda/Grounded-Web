"""Builds the footer appended to an answer: opened pages, then what the check found."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .verify import Report

_TEXT = {
    "en": {
        "sources": "Sources (opened pages):",
        "earlier": "Also used, opened earlier in this conversation:",
        "snippets": "No page opened: this answer relies on search snippets only.",
        "no_page": "No page could be read.",
        "all_one": "✓ The number in this answer appears in the opened pages.",
        "all_many": "✓ All {total} numbers in this answer appear in the opened pages.",
        "missing_one": "⚠ 1 of the {total} numbers in this answer is not in the opened pages: {items}",
        "missing_many": "⚠ {n} of the {total} numbers in this answer are not in the opened pages: {items}",
        "conflict": "⚠ The pages give different values after “{context}”: {values}",
        "all_one_snippets": "✓ The number in this answer appears in the search snippets (no page was opened).",
        "all_many_snippets": "✓ All {total} numbers in this answer appear in the search snippets (no page was opened).",
        "missing_one_snippets": "⚠ 1 of the {total} numbers in this answer is not in the search snippets: {items}",
        "missing_many_snippets": "⚠ {n} of the {total} numbers in this answer are not in the search snippets: {items}",
        "conflict_snippets": "⚠ The snippets give different values after “{context}”: {values}",
    },
    "fr": {
        "sources": "Sources (pages ouvertes) :",
        "earlier": "Aussi utilisées, ouvertes plus tôt dans la conversation :",
        "snippets": "Aucune page ouverte : réponse basée sur les extraits de recherche.",
        "no_page": "Aucune page n'a pu être lue.",
        "all_one": "✓ La valeur chiffrée de la réponse figure dans les pages ouvertes.",
        "all_many": "✓ Les {total} valeurs chiffrées de la réponse figurent dans les pages ouvertes.",
        "missing_one": "⚠ 1 valeur chiffrée sur {total} ne figure pas dans les pages ouvertes : {items}",
        "missing_many": "⚠ {n} valeurs chiffrées sur {total} ne figurent pas dans les pages ouvertes : {items}",
        "conflict": "⚠ Les pages donnent des valeurs différentes après « {context} » : {values}",
        "all_one_snippets": "✓ La valeur chiffrée de la réponse figure dans les extraits de recherche (aucune page ouverte).",
        "all_many_snippets": "✓ Les {total} valeurs chiffrées de la réponse figurent dans les extraits de recherche (aucune page ouverte).",
        "missing_one_snippets": "⚠ 1 valeur chiffrée sur {total} ne figure pas dans les extraits de recherche : {items}",
        "missing_many_snippets": "⚠ {n} valeurs chiffrées sur {total} ne figurent pas dans les extraits de recherche : {items}",
        "conflict_snippets": "⚠ Les extraits donnent des valeurs différentes après « {context} » : {values}",
    },
}

_FRENCH_WORDS = re.compile(r"\b(?:le|la|les|des|est|une|avec|pour|dans|sur|pas|qui|que|du|et)\b", re.IGNORECASE)
_ENGLISH_WORDS = re.compile(r"\b(?:the|is|are|with|for|in|on|not|which|that|of|and)\b", re.IGNORECASE)


def _answer_language(text: str) -> str:
    return "fr" if len(_FRENCH_WORDS.findall(text)) > len(_ENGLISH_WORDS.findall(text)) else "en"


def language_of(text: str, setting: str = "auto") -> str:
    """auto: Hermes's display.language, like Hermes's own trailers (other languages get English).
    answer: the language the answer is written in. en / fr: fixed."""
    if setting in _TEXT:
        return setting
    if setting == "auto":
        try:
            from agent.i18n import get_language
            lang = (get_language() or "en").lower().split("-")[0]
            return lang if lang in _TEXT else "en"
        except Exception:  # noqa: BLE001 - outside Hermes (tests, tools): fall back to the answer
            pass
    return _answer_language(text)


def _site(url: str) -> str:
    host = urlparse(url).netloc
    return host[4:] if host.startswith("www.") else host or url


def build(opened: list[str], searched: bool, report: Report | None, lang: str, show_sources: bool = True,
          basis: str = "pages", earlier: list[str] | None = None) -> str:
    """basis: "pages" when the report checked opened pages, "snippets" when only search results.
    earlier: pages from previous turns whose values the answer uses."""
    t = _TEXT[lang]
    suffix = "_snippets" if basis == "snippets" else ""
    lines: list[str] = []
    if show_sources:
        if opened:
            lines.append(t["sources"])
            lines.extend(f"- {url}" for url in opened)
        if earlier:
            lines.append(t["earlier"])
            lines.extend(f"- {url}" for url in earlier)
        if not opened and not earlier:
            lines.append(t["snippets"] if searched else t["no_page"])
    if report is not None and report.checked:
        if lines:
            lines.append("")
        total, n = len(report.checked), len(report.missing)
        if not n:
            lines.append(t[("all_one" if total == 1 else "all_many") + suffix].format(total=total))
        else:
            items = ", ".join(f.text for f in report.missing)
            lines.append(t[("missing_one" if n == 1 else "missing_many") + suffix].format(n=n, total=total, items=items))
        for c in report.conflicts:
            values = ", ".join(f"{v} ({_site(u)})" for u, v in c.found.items())
            lines.append(t["conflict" + suffix].format(context=c.context, values=values))
    return "\n".join(lines)
