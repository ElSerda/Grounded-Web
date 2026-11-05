"""grounded-web: reads web pages on this machine and lists the pages a web answer used.

Hooks only, no extra model call:
  pre_llm_call          starts a fresh record for the turn and adds a one-sentence reminder
  pre_tool_call         sends back a web_extract call that asks for several URLs at once (one URL
                        per call keeps each page within a small model's context), and notes the
                        question so a long page has its relevant passages first (focus.py)
  post_tool_call        keeps the text of every page web_extract returned, for the whole session
  transform_llm_output  appends the opened pages to the answer (append-only,
                        so a streamed answer is not reprinted)
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from . import compat, focus, footer, values

# Page text is kept in memory per session, so an answer can rely on a page opened in an
# earlier turn. Bounded: oldest pages, then oldest sessions, are dropped first. (Hermes's
# on_session_end fires after every turn, so it cannot be used to forget a session.)
MAX_PAGES_PER_SESSION = 30
MAX_SESSIONS = 20

_lock = threading.Lock()
_turns: dict[str, dict[str, Any]] = {}
_sessions: "OrderedDict[str, OrderedDict[str, tuple[str, str]]]" = OrderedDict()  # url -> (title, text)
_questions: "OrderedDict[str, list[str]]" = OrderedDict()  # session -> user message, then search queries
_ctx = None


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


# Added to the user's message, a trusted position: inside a tool result Hermes marks text as data
# the model must not follow. Small models otherwise answer from snippets that happen to hold numbers.
REMINDER = (
    "[grounded-web] If you search the web for this message: search snippets are not sources. "
    "Open the most relevant results with web_extract, one URL per call, before answering. "
    "The pages you open are listed under your answer."
)


def _start_turn(session_id: str = "", user_message: Any = "", **_: Any) -> Optional[str]:
    # An interrupted turn never reaches the transform hook, so its record is dropped here.
    with _lock:
        _turns.pop(session_id, None)
        _questions[session_id] = [str(user_message or "")[:2000]]
        _questions.move_to_end(session_id)
        while len(_questions) > MAX_SESSIONS:
            _questions.popitem(last=False)
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


def _urls(args: Any) -> list[str]:
    urls = (args or {}).get("urls") if isinstance(args, dict) else None
    if isinstance(urls, str):
        return [urls]
    return [str(u) for u in urls or [] if u]


def _guard_tool(tool_name: str = "", args: Any = None, session_id: str = "", **_: Any) -> Optional[dict]:
    if tool_name != "web_extract":
        return None
    urls = _urls(args)
    if len(urls) > 1 and _setting("one_url_per_call", True):
        return {"action": "block", "message": (
            f"grounded-web: web_extract takes one URL per call, so each page fits in your context. "
            f"Call web_extract with urls=[\"{urls[0]}\"] now, then each other URL in its own call.")}
    if urls and _setting("focus", True):
        with _lock:
            texts = list(_questions.get(session_id, []))
        limit = (args or {}).get("char_limit") if isinstance(args, dict) else None
        try:
            window = max(2_000, min(int(limit), 500_000)) if limit is not None else focus.hermes_window()
        except (TypeError, ValueError):
            window = focus.hermes_window()
        focus.expect(urls[0], focus.terms_of(*texts), window)
    return None


def _record_tool(tool_name: str = "", result: Any = None, session_id: str = "", args: Any = None,
                 **_: Any) -> None:
    if tool_name not in ("web_search", "web_extract"):
        return
    if tool_name == "web_search" and isinstance(args, dict) and args.get("query"):
        with _lock:
            texts = _questions.setdefault(session_id, [""])
            texts.append(str(args["query"])[:300])
            del texts[1:-3]  # the user's message and the last three queries
    pages = _pages(result) if tool_name == "web_extract" else []
    with _lock:
        turn = _turns.setdefault(session_id, {"opened": [], "searched": False})
        if tool_name == "web_search":
            turn["searched"] = True
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
    if mode == "never":
        return None
    if mode == "auto" and compat.other_reply_rewriters("grounded-web", getattr(_ctx, "has_plugin", None)):
        return None
    titles = {u: t for u, (t, _) in known.items()}
    # Pages from earlier turns are listed only when the answer uses one of their values.
    earlier_pages = [{"url": u, "content": c} for u, (_, c) in known.items() if u not in turn["opened"]]
    earlier = values.pages_used(response_text, earlier_pages) if earlier_pages else []
    lang = footer.language_of(response_text, _setting("language", "auto"))
    text = footer.build(turn["opened"], turn["searched"], lang, earlier, titles)
    # Keep the answer byte for byte: Hermes then prints only the added footer after a streamed reply.
    return f"{response_text}\n\n{text}" if text else None


def register(ctx) -> None:
    global _ctx
    _ctx = ctx
    ctx.register_hook("pre_llm_call", _start_turn)
    ctx.register_hook("pre_tool_call", _guard_tool)
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
