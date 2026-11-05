"""Extraction helpers that need no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pkg import load  # noqa: E402

import importlib  # noqa: E402

load()
ex = importlib.import_module("grounded_web.extract")

MAIN = "Game Changer\nGear up with the GeForce GPU X and AI-powered DLSS. " * 10
BROWSER = """
# GPU X
[Shop now](https://shop.example/gpu-x)
## Specs
| Spec | Value |
| --- | --- |
| CUDA Cores | 10752 |
| Boost Clock (GHz) | 2.62 |
| Maximum Digital Resolution | 4K at 480Hz or 8K at 165Hz with DSC |
| Total Graphics Power (W) | 360 |
## Footer
[Privacy](https://maker.example/privacy) © 2026
"""


def test_complement_adds_only_rows_with_new_values():
    extra = ex.complement(MAIN, BROWSER)
    assert "## Specs" in extra
    assert "| CUDA Cores | 10752 |" in extra
    assert "8K at 165Hz" in extra
    assert "Shop now" not in extra and "Privacy" not in extra
    assert "http" not in extra


def test_complement_skips_values_already_in_main_text():
    assert "10752" not in ex.complement(MAIN + " It has 10752 cores.", BROWSER)


def test_merge_uses_browser_text_when_main_text_is_empty():
    content, engine = ex.merge("", BROWSER)
    assert engine == "crawl4ai" and "8K at 165Hz" in content and "](" not in content


def test_merge_appends_complement():
    content, engine = ex.merge(MAIN, BROWSER)
    assert engine == "trafilatura+crawl4ai"
    assert content.startswith(MAIN)
    assert "More values from this page" in content


def test_merge_without_browser():
    assert ex.merge(MAIN, "") == (MAIN, "trafilatura")


def test_block_and_error_pages():
    assert ex.looks_blocked("Just a moment...", "Checking your browser before accessing.")
    assert ex.looks_blocked("Page introuvable", "Désolé, cette page n'existe plus.")
    assert ex.looks_blocked("Oops", "404 - the page you requested was not found")
    assert ex.looks_blocked("Access Denied", "You don't have permission to access this server.")


def test_error_codes_need_their_context():
    for title, text in [("Error 404", "Sorry."), ("Oops", "HTTP 404"), ("Not here", "404 Not Found"),
                        ("Gone", "410 Gone: this item was removed."), ("Erreur", "Erreur 404 : page introuvable")]:
        assert ex.looks_blocked(title, text), (title, text)


def test_a_short_table_with_the_number_404_is_content():
    # Found with Nemotron: an air travel CSV (404 passengers in September 1958) lost its footer line.
    csv = ("| Month | 1958 | 1959 |\n| --- | --- | --- |\n| AUG | 505 | 559 |\n"
           "| SEP | 404 | 463 |\n| OCT | 410 | 407 |")
    assert ex.looks_blocked("airtravel.csv", csv) == ""
    assert ex.looks_blocked("Price list", "Model A: 404 EUR. Model B: 410 EUR.") == ""


def test_long_pages_are_never_called_blocked():
    assert ex.looks_blocked("HTTP 404 explained", "The 404 status code means not found. " * 60) == ""


def test_normal_short_page_is_kept():
    assert ex.looks_blocked("llama.cpp 0.8.0", "Release notes: faster CUDA kernels.") == ""


def test_bot_wall_is_caught_even_on_a_long_page():
    wall = "Automated bot check in progress\nThis should only take a few seconds.\nDrag the handle to the target\n"
    assert ex.looks_blocked("TechPowerUp", wall + "filler text " * 300)


def test_unlabeled_number_rows_are_not_added():
    md = "## Benchmarks\n117.5 1%\n240 fps (37%)\n| Memory Speed | 30000 effective |"
    extra = ex.complement("Some text about the card.", md)
    assert "117.5" not in extra and "240 fps" not in extra
    assert "Memory Speed" in extra


def test_page_failures_use_hermes_origin_wording():
    # Hermes skips its keyless rescue for "HTTP <code> from origin" errors.
    assert ex._origin(200, "error or block page").startswith("HTTP 200 from origin: ")
    assert ex._origin(0, "x").startswith("HTTP 200 from origin")
    assert ex._origin(403, "bot wall").startswith("HTTP 403 from origin: ")


ARTICLE_HEAD = '<html><head><meta property="og:type" content="article"><title>Error 404</title></head><body><article>'


def test_a_troll_post_titled_error_404_is_content():
    text = "Error 404: my motivation was not found this morning. Coffee fixed it."
    assert ex.looks_blocked("Error 404", text, {}, ARTICLE_HEAD + text + "</article>") == ""


def test_an_article_about_captchas_or_access_denied_is_content():
    text = ("Access denied, captcha, security check: why websites test you. " + "A long explanation. " * 120)
    assert ex.looks_blocked("Why websites test you", text) == ""  # long page, words not in the title
    head = '<html><head><meta property="article:published_time" content="2026-01-01"></head>'
    assert ex.looks_blocked("Access denied: a short story", "A tale.", {}, head) == ""  # an article says so


def test_a_cloudflare_challenge_header_is_a_wall_whatever_the_text():
    assert ex.looks_blocked("Docs", "Real looking text. " * 200, {"CF-Mitigated": "challenge"})


def test_challenge_phrases_still_count_on_long_pages_but_plain_words_do_not():
    assert ex.looks_blocked("Example", "Checking your browser before accessing example.com. " + "x " * 2000)
    assert ex.looks_blocked("Example", "We added a captcha to the sign-up form. " + "More text. " * 300) == ""


def test_a_long_page_about_captchas_keeps_its_title():
    assert ex.looks_blocked("CAPTCHA - Wikipedia", "A CAPTCHA is a type of challenge-response test. " * 60) == ""
    assert ex.looks_blocked("Access Denied", "You don't have permission to access this server.")  # short: a wall
