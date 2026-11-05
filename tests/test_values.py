"""Value spotting, used to tell which pages an answer relies on and which browser lines to keep."""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pkg import load  # noqa: E402

load()
values = importlib.import_module("grounded_web.values")

OFFICIAL = {
    "url": "https://maker.example/gpu-x",
    "content": (
        "| Spec | Value |\n"
        "| CUDA Cores | 10,752 |\n"
        "| AI TOPS | 1801 |\n"
        "| Memory Bandwidth | 1,344 GB/sec |\n"
        "| Total Graphics Power (W) | 360 |\n"
        "| Memory Interface Width | 256-bit |\n"
        "Single-Precision Performance\n65.3 TFLOPS¹\n"
        "Starting at $999.\n"
    ),
}
OTHER = {"url": "https://other.example/x", "content": "Nothing relevant here, 2024."}


def used(answer):
    return values.pages_used(answer, [OFFICIAL, OTHER])


def test_spellings_and_units_written_differently_still_match():
    for answer in ("1 344 Go/s", "1801 TOPS", "65,3 TFLOPS", "999 $", "interface 256‑bit"):
        assert used(answer) == [OFFICIAL["url"]], answer


def test_unit_must_match():
    assert used("Elle a 360 Go de mémoire.") == []  # 360 is on the page, but as watts


def test_versions_including_at_sentence_end():
    pages = [{"url": "https://repo.example/releases", "content": "Release b12061 is out. Stable: v0.8.0"}]
    assert values.pages_used("La dernière version stable est 0.8.0.", pages) == [pages[0]["url"]]
    assert values.pages_used("La dernière build est b12061.", pages) == [pages[0]["url"]]
    assert values.pages_used("La dernière version est v0.5.2.", pages) == []


def test_model_sizes_and_context_lengths():
    pages = [{"url": "https://models.example", "content": "Sizes 14B, 70B and 405B, with a 128K context."}]
    assert values.pages_used("A 70B model with 128K tokens.", pages) == [pages[0]["url"]]
    assert values.pages_used("A 7B model.", pages) == []


def test_bare_numbers_do_not_mark_a_page_as_used():
    assert used("Il y a 10 752 cœurs.") == []


def test_small_numbers_codes_and_model_sources_are_skipped():
    assert values.extract_facts("Tensor Cores de 5e génération, 3 encodeurs, 2 à 3 fois moins.") == []
    assert [f.text for f in values.extract_facts("Puce GB203-400-A1, connecteur 12V-2×6.")] == []
    answer = "Puissance : 360 W.\n\nSources : [TechPowerUp (403 - Accès refusé)](https://x.example/2024/11)"
    assert [f.text for f in values.extract_facts(answer)] == ["360 W"]
