"""PDF reading in a child process: real text comes back, a stuck reader is stopped."""

import asyncio
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pkg import load  # noqa: E402

load()
ex = importlib.import_module("grounded_web.extract")
pytest.importorskip("pypdf")


def tiny_pdf(text: str) -> bytes:
    """A one-page PDF with one line of text, built by hand (no PDF library needed)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_pdf_text_comes_back_from_the_child_process():
    text = asyncio.run(ex.pdf_text_isolated(tiny_pdf("Total power 360 W")))
    assert text.startswith("[page 1]") and "360 W" in text


def test_a_stuck_reader_is_stopped(tmp_path, monkeypatch):
    stuck = tmp_path / "stuck.py"
    stuck.write_text("import time\ntime.sleep(30)\n")
    monkeypatch.setattr(ex, "PDF_READER", stuck)
    monkeypatch.setattr(ex, "PDF_TIMEOUT", 1)
    with pytest.raises(RuntimeError, match="stopped after 1s"):
        asyncio.run(ex.pdf_text_isolated(b"%PDF-1.4"))


def test_a_broken_pdf_is_an_error_not_a_crash():
    with pytest.raises(RuntimeError):
        asyncio.run(ex.pdf_text_isolated(b"%PDF-1.4 not really a pdf"))
