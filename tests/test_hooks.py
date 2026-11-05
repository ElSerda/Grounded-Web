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
REVIEW = {"url": "https://review.example/gpu", "content": "Boost clock 2.62 GHz, L2 cache 64 MB."}


def run_turn(ctx, answer, tools, session="s1"):
    h = ctx.hooks
    h["pre_llm_call"](session_id=session, user_message="q")
    for name, result in tools:
        h["post_tool_call"](tool_name=name, args={}, result=result, session_id=session)
    return h["transform_llm_output"](response_text=answer, session_id=session, model="m", platform="cli")


def setup(settings=None):
    gw._sessions.clear()
    gw._turns.clear()
    ctx = FakeCtx(settings)
    gw.register(ctx)
    return ctx


def test_footer_lists_the_opened_pages_with_titles():
    ctx = setup()
    page = dict(PAGE, title="GPU X | Maker")
    answer = "La carte consomme 360 W et coûte 999 $."
    out = run_turn(ctx, answer, [("web_search", "{}"), ("web_extract", extract_result(page))])
    assert out == answer + "\n\nSources (pages ouvertes) :\n- GPU X | Maker: https://maker.example/gpu"


def test_english_answer_gets_english_footer():
    ctx = setup()
    out = run_turn(ctx, "The card draws 360 W.", [("web_extract", extract_result(PAGE))])
    assert out.endswith("Sources (opened pages):\n- https://maker.example/gpu")


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


def test_bot_wall_returned_as_content_is_not_a_source():
    # Hermes's keyless rescue can bring a bot wall back as page content.
    ctx = setup()
    wall = {"url": "https://wall.example/specs", "title": "Specs | Wall",
            "content": "# Specs\n\n# Automated bot check in progress\n\nDrag the handle to the target"}
    out = run_turn(ctx, "The card draws 360 W.", [("web_extract", extract_result(wall, PAGE))])
    assert "wall.example" not in out
    assert "maker.example" in out


def test_turn_without_web_tools_is_left_alone():
    ctx = setup()
    assert run_turn(ctx, "Bonjour.", [("read_file", "{}")]) is None


def test_earlier_page_is_listed_only_when_the_answer_uses_it():
    ctx = setup()
    run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(PAGE))])
    out = run_turn(ctx, "Boost à 2,62 GHz et 360 W.", [("web_extract", extract_result(REVIEW))])
    assert "Sources (pages ouvertes) :\n- https://review.example/gpu" in out
    assert out.endswith("Aussi utilisées, ouvertes plus tôt dans la conversation :\n- https://maker.example/gpu")
    out = run_turn(ctx, "Boost à 2,62 GHz.", [("web_extract", extract_result(REVIEW))])
    assert "maker.example" not in out


def test_follow_up_without_web_tools_lists_the_earlier_page_it_uses():
    # Found with Nemotron: "and how much power does it draw?" answered from the page opened before.
    ctx = setup()
    run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(PAGE))])
    out = run_turn(ctx, "La carte consomme 360 W et il faut une alimentation de 850 W.", [])
    assert out.endswith("Aussi utilisées, ouvertes plus tôt dans la conversation :\n- https://maker.example/gpu")
    assert "Sources (pages ouvertes)" not in out
    assert run_turn(ctx, "Avec plaisir.", []) is None  # no value from the page: nothing added


def test_resumed_conversation_gets_its_earlier_pages_from_the_history():
    ctx = setup()  # a new process: the plugin has no memory of the conversation
    history = [
        {"role": "user", "content": "specs?"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "web_extract", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "<untrusted_tool_result>\n" + extract_result(PAGE) + "\n</untrusted_tool_result>"},
        {"role": "tool", "tool_call_id": "c2", "content": extract_result(REVIEW)},  # not web_extract: ignored
        {"role": "assistant", "content": "It draws 360 W."},
    ]
    h = ctx.hooks
    h["pre_llm_call"](session_id="s9", user_message="and the power?", conversation_history=history)
    out = h["transform_llm_output"](response_text="La carte consomme 360 W et le boost est à 2,62 GHz.", session_id="s9", model="m", platform="cli")
    assert out.endswith("Aussi utilisées, ouvertes plus tôt dans la conversation :\n- https://maker.example/gpu")
    assert "review.example" not in out


def test_reminder_asks_the_model_not_to_write_the_list():
    ctx = setup()
    assert "do not write that list yourself" in ctx.hooks["pre_llm_call"](session_id="s1", user_message="q")


def test_sessions_do_not_share_pages():
    ctx = setup()
    run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(PAGE))], session="a")
    out = run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(REVIEW))], session="b")
    assert "maker.example" not in out


def test_reminder_is_added_to_each_turn_and_can_be_turned_off():
    ctx = setup()
    assert "snippets are not sources" in ctx.hooks["pre_llm_call"](session_id="s1", user_message="q")
    ctx = setup({"remind": False})
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="q") is None


def test_footer_can_follow_the_answer_language():
    ctx = setup({"language": "answer"})
    out = run_turn(ctx, "The card draws 360 W.", [("web_extract", extract_result(PAGE))])
    assert "Sources (opened pages):" in out


def test_steps_aside_for_another_reply_rewriter(monkeypatch):
    monkeypatch.setattr(gw.compat, "other_reply_rewriters", lambda own, has_plugin: ["other-footer"])
    ctx = setup()
    assert run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(PAGE))]) is None
    ctx = setup({"show_sources": "always"})
    assert "maker.example" in run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(PAGE))])


def test_sources_mode_values():
    m = gw.compat.sources_mode
    assert [m(True), m(False), m("on"), m("off"), m("always"), m("never"), m(None), m("weird")] == [
        "auto", "never", "always", "never", "always", "never", "auto", "auto"]


def test_never_turns_the_footer_off():
    ctx = setup({"show_sources": "never"})
    assert run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(PAGE))]) is None
