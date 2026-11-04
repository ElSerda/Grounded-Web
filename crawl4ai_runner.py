"""Opens one URL with Crawl4AI and prints one JSON line. Runs in grounded-web's isolated environment.

Kept out of Hermes's own environment because Crawl4AI pulls about 35 packages and a browser.
Output: {"success", "status", "title", "markdown", "error"}; markdown is Crawl4AI's pruned
("fit") markdown, falling back to the full markdown when pruning leaves almost nothing.
"""

import asyncio
import json
import sys
import warnings

warnings.filterwarnings("ignore")


async def main(url: str) -> dict:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

    try:
        from crawl4ai.content_filter_strategy import PruningContentFilterLXML as Pruning
    except ImportError:  # older Crawl4AI
        from crawl4ai.content_filter_strategy import PruningContentFilter as Pruning

    run = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=45_000,
        markdown_generator=DefaultMarkdownGenerator(content_filter=Pruning()),
        verbose=False,
    )
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as crawler:
        r = await crawler.arun(url=url, config=run)
    if not r.success:
        return {"success": False, "status": r.status_code, "error": str(r.error_message or "crawl failed")[:300]}
    md = r.markdown
    fit = (md.fit_markdown or "") if md else ""
    full = (md.raw_markdown or "") if md else ""
    title = ((r.metadata or {}).get("title") or "") if isinstance(r.metadata, dict) else ""
    return {"success": True, "status": r.status_code, "title": title, "markdown": fit if len(fit) > 200 else full}


if __name__ == "__main__":
    try:
        result = asyncio.run(main(sys.argv[1]))
    except Exception as exc:  # noqa: BLE001 - reported to the caller as the page's error
        result = {"success": False, "error": f"{exc.__class__.__name__}: {exc}"[:300]}
    sys.stdout.write("\n" + json.dumps(result) + "\n")  # ASCII-only: the console code page varies
