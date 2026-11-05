"""grounded-web: shows which pages a web answer used, and checks the answer's values against them.

Hooks only, no extra model call:
  pre_llm_call          starts a fresh record for the turn
  post_tool_call        keeps the text of every page web_extract returned
  transform_llm_output  appends the opened pages and the check to the answer (append-only,
                        so a streamed answer is not reprinted)
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Optional

from . import footer, verify

_lock = threading.Lock()
_turns: dict[str, dict[str, Any]] = {}
_ctx = None


def _setting(key: str, default):
    try:
        return _ctx.get_config(key, default=default) if _ctx is not None else default
    except Exception:  # noqa: BLE001 - a settings problem must never break a turn
        return default


def _pages(result: Any) -> list[dict]:
    """Pages with content from a web_extract result. The JSON can sit inside a text envelope."""
    text = str(result or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return []
    pages = data.get("results") if isinstance(data, dict) else None
    return [
        {"url": p["url"], "content": str(p["content"])}
        for p in pages or []
        if isinstance(p, dict) and p.get("url") and p.get("content") and not p.get("error")
    ]


def _snippets(result: Any) -> list[dict]:
    """Search hits as pseudo-pages (title + description), from a web_search result."""
    text = str(result or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return []
    hits = ((data.get("data") or {}).get("web") if isinstance(data, dict) else None) or []
    return [
        {"url": h["url"], "content": f"{h.get('title', '')}\n{h.get('description', '')}"}
        for h in hits if isinstance(h, dict) and h.get("url")
    ]


# Added to the user's message, a trusted position: inside a tool result Hermes marks text as data
# the model must not follow. Small models otherwise answer from snippets that happen to hold numbers.
REMINDER = (
    "[grounded-web] If you search the web for this message: search snippets are not sources. "
    "Open the most relevant results with web_extract, one URL per call, before answering. "
    "Your answer is checked against the pages you open."
)


def _start_turn(session_id: str = "", **_: Any) -> Optional[str]:
    # An interrupted turn never reaches the transform hook, so its pages are dropped here.
    with _lock:
        _turns.pop(session_id, None)
    return REMINDER if _setting("remind", True) else None


def _record_tool(tool_name: str = "", result: Any = None, session_id: str = "", **_: Any) -> None:
    if tool_name not in ("web_search", "web_extract"):
        return
    pages = _pages(result) if tool_name == "web_extract" else []
    hits = _snippets(result) if tool_name == "web_search" else []
    with _lock:
        turn = _turns.setdefault(session_id, {"pages": {}, "searched": False, "snippets": {}})
        if tool_name == "web_search":
            turn["searched"] = True
        for hit in hits:
            turn["snippets"].setdefault(hit["url"], hit["content"])
        for page in pages:
            turn["pages"].setdefault(page["url"], page["content"])


def _append_footer(response_text: str = "", session_id: str = "", **_: Any) -> Optional[str]:
    with _lock:
        turn = _turns.pop(session_id, None)
    if turn is None or not response_text:
        return None
    pages = [{"url": u, "content": c} for u, c in turn["pages"].items()]
    # No page opened: check against the search snippets instead, and say so.
    basis = "pages" if pages else "snippets"
    if not pages:
        pages = [{"url": u, "content": c} for u, c in turn.get("snippets", {}).items()]
    report = verify.check(response_text, pages) if pages and _setting("verify", True) else None
    lang = footer.language_of(response_text, _setting("language", "auto"))
    text = footer.build(list(turn["pages"]), turn["searched"], report, lang, _setting("show_sources", True), basis)
    # Keep the answer byte for byte: Hermes then prints only the added footer after a streamed reply.
    return f"{response_text}\n\n{text}" if text else None


def register(ctx) -> None:
    global _ctx
    _ctx = ctx
    ctx.register_hook("pre_llm_call", _start_turn)
    ctx.register_hook("post_tool_call", _record_tool)
    ctx.register_hook("transform_llm_output", _append_footer)
    skills = Path(__file__).parent / "skills"
    if hasattr(ctx, "register_skill") and skills.is_dir():
        for child in sorted(skills.iterdir()):
            if (child / "SKILL.md").is_file():
                ctx.register_skill(child.name, child / "SKILL.md")  # loads as grounded-web:<name>
    if hasattr(ctx, "register_cli_command"):
        from . import cli
        cli.register(ctx)
    # The extraction backend needs Hermes's provider base class; hooks work without it.
    try:
        from .provider import GroundedWebProvider
    except ImportError:
        return
    ctx.register_web_search_provider(GroundedWebProvider())
