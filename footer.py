"""Builds the footer appended to an answer: opened pages, then what the check found."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .verify import Report

_TEXT = {
    "en": {
        "sources": "Sources (opened pages):",
        "snippets": "No page opened: this answer relies on search snippets only.",
        "no_page": "No page could be read.",
        "checked": "Check: {found} of {total} values found in these pages.",
        "missing": "Not in the opened pages: {items}",
        "conflict": "Pages disagree after “{context}”: {values}",
        "checked_snippets": "Check against the search snippets only: {found} of {total} values found.",
        "missing_snippets": "Not in the snippets: {items}",
        "conflict_snippets": "Snippets disagree after “{context}”: {values}",
    },
    "fr": {
        "sources": "Sources (pages ouvertes) :",
        "snippets": "Aucune page ouverte : réponse basée sur les extraits de recherche.",
        "no_page": "Aucune page n'a pu être lue.",
        "checked": "Vérification : {found} valeurs sur {total} retrouvées dans ces pages.",
        "missing": "Absent des pages ouvertes : {items}",
        "conflict": "Les pages divergent après « {context} » : {values}",
        "checked_snippets": "Vérification sur les seuls extraits de recherche : {found} valeurs sur {total} retrouvées.",
        "missing_snippets": "Absent des extraits : {items}",
        "conflict_snippets": "Les extraits divergent après « {context} » : {values}",
    },
}

_FRENCH_WORDS = re.compile(r"\b(?:le|la|les|des|est|une|avec|pour|dans|sur|pas|qui|que|du|et)\b", re.IGNORECASE)
_ENGLISH_WORDS = re.compile(r"\b(?:the|is|are|with|for|in|on|not|which|that|of|and)\b", re.IGNORECASE)


def language_of(text: str, setting: str = "auto") -> str:
    if setting in _TEXT:
        return setting
    return "fr" if len(_FRENCH_WORDS.findall(text)) > len(_ENGLISH_WORDS.findall(text)) else "en"


def _site(url: str) -> str:
    host = urlparse(url).netloc
    return host[4:] if host.startswith("www.") else host or url


def build(opened: list[str], searched: bool, report: Report | None, lang: str, show_sources: bool = True,
          basis: str = "pages") -> str:
    """basis: "pages" when the report checked opened pages, "snippets" when only search results."""
    t = _TEXT[lang]
    suffix = "_snippets" if basis == "snippets" else ""
    lines: list[str] = []
    if show_sources:
        if opened:
            lines.append(t["sources"])
            lines.extend(f"- {url}" for url in opened)
        else:
            lines.append(t["snippets"] if searched else t["no_page"])
    if report is not None and report.checked:
        if lines:
            lines.append("")
        lines.append(t["checked" + suffix].format(found=len(report.grounded), total=len(report.checked)))
        if report.missing:
            lines.append(t["missing" + suffix].format(items=", ".join(f.text for f in report.missing)))
        for c in report.conflicts:
            values = " / ".join(f"{v} ({_site(u)})" for u, v in c.found.items())
            lines.append(t["conflict" + suffix].format(context=c.context, values=values))
    return "\n".join(lines)
