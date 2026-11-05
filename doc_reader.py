"""Reads one document with anydoc, Hermes's own document converter (the one `read_file` uses).

    python doc_reader.py [max_chars] < document     ->  {"text": "..."} or {"error": "..."} (one ASCII JSON line)

PDF, Word, PowerPoint, Excel, OpenDocument, EPUB and RTF become Markdown, tables included.
Run as a child process by extract.document_text_isolated: anydoc is native code, and a crafted
file must not hang or crash Hermes. Standalone on purpose: no imports from the plugin.
"""

import json
import sys


def document_text(data: bytes, max_chars: int = 30_000) -> dict:
    import anydoc

    try:
        text = anydoc.to_markdown_bytes(data)
    except Exception as exc:  # noqa: BLE001 - every anydoc failure is a page error for the caller
        kind = type(exc).__name__
        if kind == "NeedsOcrError":
            return {"error": "scanned document with no text layer (needs OCR)"}
        if kind == "EncryptedError":
            return {"error": "encrypted document"}
        return {"error": f"{kind}: {exc}"[:300]}
    return {"text": (text or "").strip()[:max_chars]}


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 30_000
    sys.stdout.write(json.dumps(document_text(sys.stdin.buffer.read(), limit)) + "\n")
