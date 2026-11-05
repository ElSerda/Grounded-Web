"""Hook flow tests with a fake Hermes context."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pkg import load  # noqa: E402

gw = load()


class FakeCtx:
    def __init__(self, settings=None):
        self.hooks = {}
        self.settings = settings or {}

    def register_hook(self, name, fn, **_):
        self.hooks[name] = fn

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


def extract_result(*pages):
    return json.dumps({"results": [dict(p) for p in pages]})


PAGE = {"url": "https://maker.example/gpu", "content": "Total Graphics Power: 360 W. Memory: 16 GB GDDR7."}


def run_turn(ctx, answer, tools):
    h = ctx.hooks
    h["pre_llm_call"](session_id="s1", user_message="q")
    for name, result in tools:
        h["post_tool_call"](tool_name=name, args={}, result=result, session_id="s1")
    return h["transform_llm_output"](response_text=answer, session_id="s1", model="m", platform="cli")


def setup(settings=None):
    ctx = FakeCtx(settings)
    gw.register(ctx)
    return ctx


def test_footer_lists_pages_and_flags_missing_value():
    ctx = setup()
    answer = "La carte consomme 360 W et a 16 Go, pour 999 $."
    out = run_turn(ctx, answer, [("web_search", "{}"), ("web_extract", extract_result(PAGE))])
    assert out.startswith(answer + "\n\n")  # append-only
    assert "Sources (pages ouvertes) :\n- https://maker.example/gpu" in out
    assert "Vérification : 2 valeurs sur 3 retrouvées dans ces pages." in out
    assert "Absent des pages ouvertes : 999 $" in out


def test_english_answer_gets_english_footer():
    ctx = setup()
    out = run_turn(ctx, "The card draws 360 W and has 16 GB of memory.", [("web_extract", extract_result(PAGE))])
    assert "Sources (opened pages):" in out
    assert "Check: 2 of 2 values found in these pages." in out
    assert "Not in the opened pages" not in out


def test_search_only_turn_says_so():
    ctx = setup()
    out = run_turn(ctx, "La carte a 16 Go.", [("web_search", "{}")])
    assert out.endswith("Aucune page ouverte : réponse basée sur les extraits de recherche.")


def test_failed_pages_are_not_listed():
    ctx = setup()
    failed = {"url": "https://blocked.example", "content": "", "error": "403"}
    out = run_turn(ctx, "La carte a 16 Go.", [("web_extract", extract_result(failed))])
    assert "blocked.example" not in out
    assert out.endswith("Aucune page n'a pu être lue.")


def test_turn_without_web_tools_is_left_alone():
    ctx = setup()
    assert run_turn(ctx, "Bonjour.", [("read_file", "{}")]) is None


def test_settings_turn_parts_off():
    ctx = setup({"verify": False, "language": "en"})
    out = run_turn(ctx, "La carte consomme 360 W, pour 999 $.", [("web_extract", extract_result(PAGE))])
    assert "Sources (opened pages):" in out
    assert "Check:" not in out


def search_result(*hits):
    return json.dumps({"success": True, "data": {"web": [dict(h) for h in hits]}})


def test_search_only_turn_is_checked_against_snippets():
    ctx = setup()
    hit = {"url": "https://maker.example/gpu", "title": "GPU X", "description": "GPU X draws 360 W, 16 GB GDDR7."}
    out = run_turn(ctx, "La carte consomme 360 W et coûte 999 $.", [("web_search", search_result(hit))])
    assert "Aucune page ouverte" in out
    assert "Vérification sur les seuls extraits de recherche : 1 valeurs sur 2 retrouvées." in out
    assert "Absent des extraits : 999 $" in out


def test_reminder_is_added_to_each_turn_and_can_be_turned_off():
    ctx = setup()
    assert "snippets are not sources" in ctx.hooks["pre_llm_call"](session_id="s1", user_message="q")
    ctx = setup({"remind": False})
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="q") is None


def test_footer_can_follow_the_answer_language():
    ctx = setup({"language": "answer"})
    out = run_turn(ctx, "The card draws 360 W.", [("web_extract", extract_result(PAGE))])
    assert "Sources (opened pages):" in out
