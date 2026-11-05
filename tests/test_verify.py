"""Verifier tests on made-up pages. Run with: python -m pytest tests"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pkg import load  # noqa: E402

verify = load().verify

OFFICIAL = {
    "url": "https://maker.example/gpu-x",
    "content": (
        "| Spec | Value |\n"
        "| CUDA Cores | 10,752 |\n"
        "| AI TOPS | 1801 |\n"
        "| Memory Bandwidth | 1,344 GB/sec |\n"
        "| Total Graphics Power (W) | 360 |\n"
        "Single-Precision Performance\n65.3 TFLOPS¹\n"
        "Maximum resolution: 4K at 480Hz or 8K at 165Hz with DSC.\n"
        "Starting at $999.\n"
    ),
}
REVIEW = {
    "url": "https://review.example/gpu-x",
    "content": "Display: 4K at 480Hz or 8K at 120Hz with DSC. Memory speed 30000 effective = 1875 MHz.",
}


def missing(answer, pages):
    return [f.text for f in verify.check(answer, pages).missing]


def test_values_in_pages_are_grounded_across_spellings():
    answer = (
        "- Cœurs CUDA : 10 752\n"
        "- Bande passante : 1 344 Go/s\n"
        "- AI : 1801 TOPS\n"
        "- Puissance : 360 W\n"
        "- FP32 : 65,3 TFLOPS\n"
        "- Prix : 999 $\n"
    )
    assert missing(answer, [OFFICIAL]) == []


def test_value_absent_from_pages_is_reported():
    assert missing("Mémoire à 30 Gbps, 14 080 cœurs.", [OFFICIAL, REVIEW]) == ["30 Gbps", "14 080"]


def test_unit_must_match():
    # 360 is on the page, but as watts, not gigabytes.
    assert missing("Elle a 360 Go de mémoire.", [OFFICIAL]) == ["360 Go"]


def test_versions_including_at_sentence_end():
    pages = [{"url": "https://repo.example/releases", "content": "Release b12061 is out. Stable: v0.8.0"}]
    assert missing("La dernière version stable est 0.8.0.", pages) == []
    assert missing("La dernière build est b12061.", pages) == []
    assert missing("La dernière version est v0.5.2.", pages) == ["v0.5.2"]


def test_small_bare_numbers_are_not_checked():
    assert verify.extract_facts("Tensor Cores de 5e génération, 3 encodeurs, 2 à 3 fois moins.") == []


def test_model_written_sources_and_links_are_ignored():
    answer = "Puissance : 360 W.\n\nSources : [TechPowerUp (403 - Accès refusé)](https://x.example/2024/11)"
    assert [f.text for f in verify.extract_facts(answer)] == ["360 W"]


def test_conflict_between_pages_is_reported():
    report = verify.check("8K à 120 Hz avec DSC.", [OFFICIAL, REVIEW])
    assert report.missing == []
    [conflict] = report.conflicts
    assert conflict.context == "or 8k at"
    assert conflict.found == {REVIEW["url"]: "120Hz", OFFICIAL["url"]: "165Hz"}


def test_no_conflict_when_pages_agree():
    assert verify.check("4K à 480 Hz.", [OFFICIAL, REVIEW]).conflicts == []


def test_product_codes_are_not_values():
    assert [f.text for f in verify.extract_facts("Puce GB203-400-A1, connecteur 12V-2×6.")] == []


def test_model_numbers_do_not_make_conflicts():
    pages = [
        {"url": "https://a.example", "content": "| GeForce RTX 360 W | yes |"},
        {"url": "https://b.example", "content": "Compared with the GeForce RTX 5090 flagship."},
    ]
    assert verify.check("Elle consomme 360 W.", pages).conflicts == []


def test_unicode_hyphen_in_units():
    pages = [{"url": "https://a.example", "content": "Memory Interface Width 256-bit"}]
    assert missing("Mémoire : 16 Go, interface 256\u2011bit.", pages + [{"url": "https://b.example", "content": "16 GB"}]) == []


def test_used_pages_are_reported():
    report = verify.check("8K à 165 Hz.", [OFFICIAL, REVIEW])
    assert report.used == [OFFICIAL["url"]]
