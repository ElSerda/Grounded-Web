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


def search_result(*hits):
    return json.dumps({"success": True, "data": {"web": [dict(h) for h in hits]}})


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


def test_footer_lists_pages_and_flags_missing_value():
    ctx = setup({"verify": True})
    answer = "La carte consomme 360 W et a 16 Go, pour 999 $."
    out = run_turn(ctx, answer, [("web_search", "{}"), ("web_extract", extract_result(PAGE))])
    assert out.startswith(answer + "\n\n")  # append-only
    assert "Sources (pages ouvertes) :\n- https://maker.example/gpu" in out
    assert "⚠ 1 valeur chiffrée sur 3 ne figure pas dans les pages ouvertes : 999 $" in out


def test_all_found_reads_plainly():
    ctx = setup({"verify": True})
    out = run_turn(ctx, "The card draws 360 W and has 16 GB of memory.", [("web_extract", extract_result(PAGE))])
    assert "Sources (opened pages):" in out
    assert "✓ All 2 numbers in this answer appear in the opened pages." in out


def test_single_number_wording():
    ctx = setup({"verify": True})
    out = run_turn(ctx, "The card draws 360 W.", [("web_extract", extract_result(PAGE))])
    assert "✓ The number in this answer appears in the opened pages." in out


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


def test_settings_turn_parts_off():
    ctx = setup({"verify": False, "language": "en"})
    out = run_turn(ctx, "La carte consomme 360 W, pour 999 $.", [("web_extract", extract_result(PAGE))])
    assert "Sources (opened pages):" in out
    assert "numbers" not in out


def test_search_only_turn_is_checked_against_snippets():
    ctx = setup({"verify": True})
    hit = {"url": "https://maker.example/gpu", "title": "GPU X", "description": "GPU X draws 360 W, 16 GB GDDR7."}
    out = run_turn(ctx, "La carte consomme 360 W et coûte 999 $.", [("web_search", search_result(hit))])
    assert "Aucune page ouverte" in out
    assert "⚠ 1 valeur chiffrée sur 2 ne figure pas dans les extraits de recherche : 999 $" in out


def test_pages_from_earlier_turns_still_count():
    ctx = setup({"verify": True})
    run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(PAGE))])
    # Second turn opens another page but also reuses the first page's values.
    out = run_turn(ctx, "Boost à 2,62 GHz, 64 Mo de cache L2 et 360 W.", [("web_extract", extract_result(REVIEW))])
    assert "Sources (pages ouvertes) :\n- https://review.example/gpu" in out
    assert "Aussi utilisées, ouvertes plus tôt dans la conversation :\n- https://maker.example/gpu" in out
    assert "✓ Les 3 valeurs chiffrées de la réponse figurent dans les pages ouvertes." in out


def test_sessions_do_not_share_pages():
    ctx = setup({"verify": True})
    run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(PAGE))], session="a")
    out = run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(REVIEW))], session="b")
    assert "maker.example" not in out
    assert "⚠ 1 valeur chiffrée sur 1" in out


def test_reminder_is_added_to_each_turn_and_can_be_turned_off():
    ctx = setup()
    assert "snippets are not sources" in ctx.hooks["pre_llm_call"](session_id="s1", user_message="q")
    ctx = setup({"remind": False})
    assert ctx.hooks["pre_llm_call"](session_id="s1", user_message="q") is None


def test_footer_can_follow_the_answer_language():
    ctx = setup({"language": "answer"})
    out = run_turn(ctx, "The card draws 360 W.", [("web_extract", extract_result(PAGE))])
    assert "Sources (opened pages):" in out


def test_default_footer_is_sources_only_with_titles():
    ctx = setup()
    page = dict(PAGE, title="GPU X | Maker")
    out = run_turn(ctx, "La carte consomme 360 W et coûte 999 $.", [("web_extract", extract_result(page))])
    assert out.endswith("Sources (pages ouvertes) :\n- GPU X | Maker: https://maker.example/gpu")
    assert "valeur" not in out.split("\n\n", 1)[1]


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


def test_never_hides_the_sources():
    ctx = setup({"show_sources": "never", "verify": True})
    out = run_turn(ctx, "La carte consomme 360 W.", [("web_extract", extract_result(PAGE))])
    assert "maker.example" not in out and "✓" in out
