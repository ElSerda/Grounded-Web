"""The `grounded-web` web_extract backend: pages and PDFs read on this machine.

Search stays with any search backend (SearXNG, DDGS, Brave...): set
`web.search_backend` to it and `web.extract_backend: grounded-web`.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from agent.web_search_provider import WebSearchProvider

from . import extract


class GroundedWebProvider(WebSearchProvider):
    @property
    def name(self) -> str:
        return "grounded-web"

    @property
    def display_name(self) -> str:
        return "grounded-web (local extraction)"

    def is_available(self) -> bool:
        # No network here: runs on every `hermes tools` paint.
        return all(importlib.util.find_spec(m) is not None for m in ("trafilatura", "pypdf", "httpx"))

    def supports_search(self) -> bool:
        return False

    def supports_extract(self) -> bool:
        return True

    async def extract(self, urls: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        # Contract from agent.web_search_provider: one dict per URL, "error" only on failure.
        # (The developer guide's {"success", "data"} envelope is outdated for extract.)
        try:
            pages = await extract.read_pages(list(urls))
        except Exception as exc:  # noqa: BLE001 - whole-call failure, reported on every URL
            error = f"grounded-web could not read the pages: {exc}"[:300]
            return [{"url": u, "title": "", "content": "", "error": error} for u in urls]
        return [p.as_result() for p in pages]
