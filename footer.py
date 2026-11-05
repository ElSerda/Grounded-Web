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
        "missing_only": "⚠ The number in this answer is not in the opened pages: {items}",
        "missing_one": "⚠ 1 of the {total} numbers in this answer is not in the opened pages: {items}",
        "missing_many": "⚠ {n} of the {total} numbers in this answer are not in the opened pages: {items}",
        "conflict": "⚠ The pages give different values after “{context}”: {values}",
        "all_one_snippets": "✓ The number in this answer appears in the search snippets (no page was opened).",
        "all_many_snippets": "✓ All {total} numbers in this answer appear in the search snippets (no page was opened).",
        "missing_only_snippets": "⚠ The number in this answer is not in the search snippets: {items}",
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
        "missing_only": "⚠ La valeur chiffrée de la réponse ne figure pas dans les pages ouvertes : {items}",
        "missing_one": "⚠ 1 valeur chiffrée sur {total} ne figure pas dans les pages ouvertes : {items}",
        "missing_many": "⚠ {n} valeurs chiffrées sur {total} ne figurent pas dans les pages ouvertes : {items}",
        "conflict": "⚠ Les pages donnent des valeurs différentes après « {context} » : {values}",
        "all_one_snippets": "✓ La valeur chiffrée de la réponse figure dans les extraits de recherche (aucune page ouverte).",
        "all_many_snippets": "✓ Les {total} valeurs chiffrées de la réponse figurent dans les extraits de recherche (aucune page ouverte).",
        "missing_only_snippets": "⚠ La valeur chiffrée de la réponse ne figure pas dans les extraits de recherche : {items}",
        "missing_one_snippets": "⚠ 1 valeur chiffrée sur {total} ne figure pas dans les extraits de recherche : {items}",
        "missing_many_snippets": "⚠ {n} valeurs chiffrées sur {total} ne figurent pas dans les extraits de recherche : {items}",
        "conflict_snippets": "⚠ Les extraits donnent des valeurs différentes après « {context} » : {values}",
    },
}

_FRENCH_WORDS = re.compile(r"\b(?:le|la|les|des|est|une|avec|pour|dans|sur|pas|qui|que|du|et)\b", re.IGNORECASE)
_ENGLISH_WORDS = re.compile(r"\b(?:the|is|are|with|for|in|on|not|which|that|of|and)\b", re.IGNORECASE)


def _answer_language(text: str) -> str:
    return "fr" if len(_FRENCH_WORDS.findall(text)) > len(_ENGLISH_WORDS.findall(text)) else "en"


def _hermes_language() -> str | None:
    """Hermes's UI language, resolved as Hermes does: HERMES_LANGUAGE > display.language > en.
    None outside Hermes (tests, tools)."""
    try:
        from agent.secret_scope import get_secret
        from hermes_cli.config import load_config_readonly
    except ImportError:
        return None
    try:
        lang = (get_secret("HERMES_LANGUAGE") or "").strip()
        if not lang:
            display = (load_config_readonly() or {}).get("display") or {}
            lang = str(display.get("language") or "en")
    except Exception:  # noqa: BLE001
        return None
    return lang.lower().replace("_", "-").split("-")[0]


def language_of(text: str, setting: str = "auto") -> str:
    """auto: Hermes's display.language, like Hermes's own trailers (other languages get English).
    answer: the language the answer is written in. en / fr: fixed."""
    if setting in _TEXT:
        return setting
    if setting == "auto":
        lang = _hermes_language()
        if lang is not None:
            return lang if lang in _TEXT else "en"
    return _answer_language(text)


def _site(url: str) -> str:
    host = urlparse(url).netloc
    return host[4:] if host.startswith("www.") else host or url


def _source_line(url: str, titles: dict[str, str]) -> str:
    """"- Page title: https://..." with the link bare, so terminals, Desktop and chat apps make it clickable."""
    title = re.sub(r"\s+", " ", titles.get(url, "")).strip()
    if len(title) > 80:
        title = title[:77].rstrip() + "..."
    return f"- {title}: {url}" if title else f"- {url}"


def build(opened: list[str], searched: bool, report: Report | None, lang: str, show_sources: bool = True,
          basis: str = "pages", earlier: list[str] | None = None, titles: dict[str, str] | None = None,
          show_check: bool = True) -> str:
    """basis: "pages" when the report checked opened pages, "snippets" when only search results.
    earlier: pages from previous turns whose values the answer uses. show_check: add the check lines."""
    t = _TEXT[lang]
    titles = titles or {}
    suffix = "_snippets" if basis == "snippets" else ""
    lines: list[str] = []
    if show_sources:
        if opened:
            lines.append(t["sources"])
            lines.extend(_source_line(url, titles) for url in opened)
        if earlier:
            lines.append(t["earlier"])
            lines.extend(_source_line(url, titles) for url in earlier)
        if not opened and not earlier:
            lines.append(t["snippets"] if searched else t["no_page"])
    if show_check and report is not None and report.checked:
        if lines:
            lines.append("")
        total, n = len(report.checked), len(report.missing)
        if not n:
            lines.append(t[("all_one" if total == 1 else "all_many") + suffix].format(total=total))
        else:
            items = ", ".join(f.text for f in report.missing)
            key = "missing_only" if total == 1 else "missing_one" if n == 1 else "missing_many"
            lines.append(t[key + suffix].format(n=n, total=total, items=items))
        for c in report.conflicts:
            values = ", ".join(f"{v} ({_site(u)})" for u, v in c.found.items())
            lines.append(t["conflict" + suffix].format(context=c.context, values=values))
    return "\n".join(lines)
