"""One URL per web_extract call, and long pages with the passages about the question first."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pkg import load  # noqa: E402

gw = load()
import grounded_web.extract as ex  # noqa: E402
import grounded_web.focus as fo  # noqa: E402

FILLER = "The architecture brings new shader features and improved efficiency for many workloads."


def long_page(table_at: int = 120) -> str:
    """A white-paper-like page: a table of contents, the flagship first, the asked product deep inside,
    its spec table split by a running page header."""
    blocks = ["Blackwell white paper", "Contents\nIntroduction......3\nGB202......14\nGB203......49"]
    blocks += [f"Section {i}. {FILLER} The flagship X90 leads the lineup." for i in range(table_at)]
    blocks += [
        "The first product using the GB203 GPU is the X80. Its specs are compared below.",
        "|Card|X70|X80|\n|---|---|---|\n|CUDA Cores|9728|10752|\n|Boost Clock (MHz)|2505|2617|",
        "APPENDIX B: GB203",
        "|Memory|16 GB GDDR6X|16 GB GDDR7|\n|Memory Bandwidth|716.8 GB/sec|960 GB/sec|",
    ]
    blocks += [f"Closing {i}. {FILLER}" for i in range(40)]
    return "\n\n".join(blocks)


def model_view(text: str, window: int = 15_000) -> str:
    """What Hermes shows the model of a long page: about the first 75% of the window (plus a tail)."""
    return text[: int(window * 0.75)]


# ---------------------------------------------------------------- focus.py


def test_terms_put_numbers_first_and_drop_stop_words_and_operators():
    terms = fo.terms_of("trouve moi les specifications techniques de la RTX 5080",
                        "RTX 5080 specs site:nvidia.com filetype:pdf")
    assert terms[0] == "5080"
    assert "rtx" in terms and "specifications" in terms
    assert not {"trouve", "moi", "les", "site", "nvidia.com", "pdf", "filetype"} & set(terms)


def test_short_page_is_unchanged():
    text = "Short page about the X80.\n\nIt has 10752 cores."
    assert fo.arrange(text, ["x80"], 15_000) == text


def test_long_page_puts_the_asked_product_where_the_model_sees_it():
    text = long_page()
    assert "10752" not in model_view(text)  # what went wrong on the homelab
    out = fo.arrange(text, fo.terms_of("specs of the X80"), 15_000)
    seen = model_view(out)
    assert "|CUDA Cores|9728|10752|" in seen
    assert "|Memory Bandwidth|716.8 GB/sec|960 GB/sec|" in seen  # the table's second half, past the page header
    assert "[grounded-web: this page is long." in seen


def test_nothing_is_removed():
    text = long_page()
    out = fo.arrange(text, ["x80"], 15_000)
    blocks = [b for b in text.split("\n\n")]
    assert all(b in out for b in blocks)


def test_table_of_contents_and_common_words_do_not_move():
    text = long_page()
    out = fo.arrange(text, ["x80", "architecture"], 15_000)
    note = out.index("[grounded-web: this page is long.")
    first_part = out[note: out.index("[grounded-web: rest of the page")]
    assert "Introduction......3" not in first_part
    assert "Section 5." not in first_part  # "architecture" is on every filler line: it weighs nothing


def test_page_without_the_terms_is_unchanged():
    text = long_page()
    assert fo.arrange(text, ["zz9000"], 15_000) == text


def test_expected_url_matches_despite_slash_and_case():
    fo.expect("https://WWW.Example.com/specs/", ["x80"], 9000)
    assert fo.take("https://www.example.com/specs") == (["x80"], 9000)


# ---------------------------------------------------------------- hooks and provider


class FakeCtx:
    def __init__(self, settings=None):
        self.hooks = {}
        self.settings = settings or {}

    def register_hook(self, name, fn, **_):
        self.hooks[name] = fn

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


def setup(settings=None):
    gw._sessions.clear()
    gw._turns.clear()
    gw._questions.clear()
    ctx = FakeCtx(settings)
    gw.register(ctx)
    return ctx


def test_several_urls_read_the_first_and_the_result_lists_the_others():
    ctx = setup()
    urls = ["https://a.example/1", "https://b.example/2", "https://c.example/3"]
    out = ctx.hooks["pre_tool_call"](tool_name="web_extract", session_id="s1", tool_call_id="c1", args={"urls": urls})
    assert out == {"action": "modify", "args": {"urls": ["https://a.example/1"]}}
    result = json.dumps({"results": [{"url": urls[0], "content": "page"}]})
    noted = json.loads(ctx.hooks["transform_tool_result"](tool_name="web_extract", result=result,
                                                          session_id="s1", tool_call_id="c1"))
    assert noted["results"][0]["url"] == urls[0]
    assert "https://b.example/2, https://c.example/3" in noted["grounded_web_note"]
    # once only, and only for that call
    assert ctx.hooks["transform_tool_result"](tool_name="web_extract", result=result, session_id="s1", tool_call_id="c1") is None


def test_one_url_passes_and_other_tools_are_untouched():
    ctx = setup()
    assert ctx.hooks["pre_tool_call"](tool_name="web_extract", args={"urls": ["https://a.example/1"]}, session_id="s1") is None
    assert ctx.hooks["pre_tool_call"](tool_name="terminal", args={"urls": ["a", "b"]}, session_id="s1") is None
    assert ctx.hooks["transform_tool_result"](tool_name="web_extract", result="{}", session_id="s1", tool_call_id="x") is None


def test_the_guard_can_be_turned_off():
    ctx = setup({"one_url_per_call": False, "focus": False})
    assert ctx.hooks["pre_tool_call"](tool_name="web_extract", args={"urls": ["https://a.example/1", "https://b.example/2"]},
                                      session_id="s1") is None


def test_question_and_search_queries_reach_the_reader():
    ctx = setup()
    h = ctx.hooks
    h["pre_llm_call"](session_id="s1", user_message="Quelles sont les specs de la X80 ?")
    h["post_tool_call"](tool_name="web_search", args={"query": "X80 GB203 specifications"}, result="{}", session_id="s1")
    h["pre_tool_call"](tool_name="web_extract", args={"urls": ["https://maker.example/whitepaper.pdf"], "char_limit": 12000},
                       session_id="s1")
    terms, window = fo.take("https://maker.example/whitepaper.pdf")
    assert window == 12000
    assert {"x80", "gb203", "specifications"} <= set(terms)


def test_the_page_handed_back_has_the_relevant_part_first():
    # What provider.extract() does with each page (the provider needs Hermes's base class).
    url = "https://maker.example/whitepaper.pdf"
    fo.expect(url, ["x80"], 15_000)
    page = ex.Page(url, "White paper", long_page(), engine="anydoc")
    result = page.as_result(*(fo.take(url) or (None, 0)))
    assert "|CUDA Cores|9728|10752|" in model_view(result["content"])
    assert len(result["content"]) <= ex.MAX_CONTENT_CHARS
    assert result["raw_content"] == result["content"]
    json.dumps(result)


def test_without_a_question_the_page_is_only_cut():
    page = ex.Page("https://maker.example/x", "X", "a" * 50_000)
    assert page.as_result()["content"] == "a" * ex.MAX_CONTENT_CHARS
