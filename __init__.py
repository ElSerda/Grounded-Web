"""grounded-web: shows which pages a web answer used, and checks the answer's values against them.

Hooks only, no extra model call:
  pre_llm_call          starts a fresh record for the turn and adds a one-sentence reminder
  post_tool_call        keeps the text of every page web_extract returned, for the whole session
  transform_llm_output  appends the opened pages and the check to the answer (append-only,
                        so a streamed answer is not reprinted)
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from . import compat, footer, verify

# Page text is kept in memory per session, so an answer can rely on a page opened in an
# earlier turn. Bounded: oldest pages, then oldest sessions, are dropped first. (Hermes's
# on_session_end fires after every turn, so it cannot be used to forget a session.)
MAX_PAGES_PER_SESSION = 30
MAX_SESSIONS = 20

_lock = threading.Lock()
_turns: dict[str, dict[str, Any]] = {}
_sessions: "OrderedDict[str, OrderedDict[str, tuple[str, str]]]" = OrderedDict()  # url -> (title, text)
_ctx = None
_own_key = "grounded-web"


def _setting(key: str, default):
    try:
        return _ctx.get_config(key, default=default) if _ctx is not None else default
    except Exception:  # noqa: BLE001 - a settings problem must never break a turn
        return default


def _payload(result: Any) -> dict:
    """The JSON object inside a tool result; Hermes may wrap it in a text envelope."""
    text = str(result or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _pages(result: Any) -> list[dict]:
    """Pages with real content from a web_extract result.

    A bot wall that another backend returned as content (Hermes's keyless rescue can do that)
    is not a source, so it is dropped here too.
    """
    from .extract import looks_blocked

    return [
        {"url": p["url"], "title": str(p.get("title") or ""), "content": str(p["content"])}
        for p in _payload(result).get("results") or []
        if isinstance(p, dict) and p.get("url") and p.get("content") and not p.get("error")
        and not looks_blocked(str(p.get("title") or ""), str(p["content"]))
    ]


def _snippets(result: Any) -> list[dict]:
    """Search hits as pseudo-pages (title + description), from a web_search result."""
    hits = (_payload(result).get("data") or {}).get("web") or []
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
    # An interrupted turn never reaches the transform hook, so its record is dropped here.
    with _lock:
        _turns.pop(session_id, None)
    return REMINDER if _setting("remind", True) else None


def _remember(session_id: str, url: str, title: str, content: str) -> None:
    pages = _sessions.setdefault(session_id, OrderedDict())
    _sessions.move_to_end(session_id)
    pages[url] = (title, content)
    pages.move_to_end(url)
    while len(pages) > MAX_PAGES_PER_SESSION:
        pages.popitem(last=False)
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)


def _record_tool(tool_name: str = "", result: Any = None, session_id: str = "", **_: Any) -> None:
    if tool_name not in ("web_search", "web_extract"):
        return
    pages = _pages(result) if tool_name == "web_extract" else []
    hits = _snippets(result) if tool_name == "web_search" else []
    with _lock:
        turn = _turns.setdefault(session_id, {"opened": [], "searched": False, "snippets": {}})
        if tool_name == "web_search":
            turn["searched"] = True
        for hit in hits:
            turn["snippets"].setdefault(hit["url"], hit["content"])
        for page in pages:
            _remember(session_id, page["url"], page["title"], page["content"])
            if page["url"] not in turn["opened"]:
                turn["opened"].append(page["url"])


def _append_footer(response_text: str = "", session_id: str = "", **_: Any) -> Optional[str]:
    with _lock:
        turn = _turns.pop(session_id, None)
        known = dict(_sessions.get(session_id, {}))
    if turn is None or not response_text:
        return None  # no web tool this turn: nothing to report
    mode = compat.sources_mode(_setting("show_sources", "auto"))
    # Hermes keeps only the first plugin rewrite of a reply: leave it to another rewriter rather
    # than hide its output, unless the user asked for this footer anyway (show_sources: always).
    if mode == "auto" and compat.other_reply_rewriters(_own_key):
        return None
    pages = [{"url": u, "content": c} for u, (_, c) in known.items()]
    titles = {u: t for u, (t, _) in known.items()}
    # No page opened in this session: check against this turn's search snippets, and say so.
    basis = "pages" if pages else "snippets"
    if not pages:
        pages = [{"url": u, "content": c} for u, c in turn["snippets"].items()]
    # Always run: it tells which earlier pages the answer relies on. Shown only with `verify` on.
    report = verify.check(response_text, pages) if pages else None
    earlier = [u for u in (report.used if report and basis == "pages" else []) if u not in turn["opened"]]
    lang = footer.language_of(response_text, _setting("language", "auto"))
    text = footer.build(turn["opened"], turn["searched"], report, lang, mode != "never", basis, earlier,
                        titles=titles, show_check=bool(_setting("verify", False)))
    # Keep the answer byte for byte: Hermes then prints only the added footer after a streamed reply.
    return f"{response_text}\n\n{text}" if text else None


def register(ctx) -> None:
    global _ctx, _own_key
    _ctx = ctx
    _own_key = getattr(ctx, "plugin_id", None) or _own_key
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
