"""Reads one PDF: `python -I pdf_reader.py [max_chars] < file.pdf` prints {"text": ...} as one ASCII JSON line.

Run as a child process by extract.pdf_text_isolated, so a crafted PDF that makes pypdf loop or
eat memory is killed without touching Hermes. Standalone on purpose: no imports from the plugin.
"""

import io
import json
import sys


def pdf_text(data: bytes, max_chars: int = 30_000) -> str:
    """Text of a PDF, in page order, as "[page N]" blocks, stopped at max_chars."""
    from pypdf import PdfReader

    parts, size = [], 0
    for i, page in enumerate(PdfReader(io.BytesIO(data)).pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(f"[page {i}]\n{text}")
            size += len(parts[-1])
        if size > max_chars:
            break
    return "\n\n".join(parts)[:max_chars]


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 30_000
    sys.stdout.write(json.dumps({"text": pdf_text(sys.stdin.buffer.read(), limit)}) + "\n")
