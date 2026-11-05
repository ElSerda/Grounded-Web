"""Reads web pages and PDFs on this machine, for web_extract.

Order for one URL:
  1. download it (HTTP errors such as 404 stop here, unless a browser can still open it);
  2. PDF -> pypdf; HTML -> trafilatura (main text, short and clean);
  3. Crawl4AI, when its isolated environment is installed, renders the same page in a
     browser. trafilatura drops what it takes for page furniture, spec tables included, so
     the lines of Crawl4AI's output that hold values missing from trafilatura's text are
     appended. When trafilatura gets nothing (script-built pages), Crawl4AI's text is used;
  4. error and block pages that answer HTTP 200 ("Page not found", "Just a moment...") are
     reported as errors, never handed to the model as content.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import values

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
FETCH_TIMEOUT = 25
BROWSER_TIMEOUT = 60
MAX_HTML_BYTES = 15 * 1024 * 1024
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_CONTENT_CHARS = 30_000  # what one page may hand to the model
MAX_COMPLEMENT_CHARS = 8_000
BROWSERS_AT_ONCE = 3  # each Crawl4AI call starts its own headless Chromium
SHORT_PAGE_CHARS = 1_500
CRAWL4AI_ENV = "grounded-web-crawl4ai"
RUNNER = Path(__file__).with_name("crawl4ai_runner.py")

# Bot walls and challenge pages: never real content, whatever the page length.
_WALL_RE = re.compile(
    r"\b(?:just a moment|attention required|checking your browser|verify(?:ing)? you are (?:a )?human|"
    r"are you a (?:robot|human)|captcha|bot check|automated (?:bot|access|traffic)|drag the handle|"
    r"ddos protection|security check|unusual traffic|access denied|accès refusé|request blocked|"
    r"please enable (?:javascript|cookies))\b",
    re.IGNORECASE,
)
# Error pages: only when the page is short, since articles mention these words too.
_ERROR_RE = re.compile(
    r"\b(?:404|410|not found|page introuvable|introuvable|n'existe (?:pas|plus)|no longer available|"
    r"forbidden|enable javascript|too many requests)\b",
    re.IGNORECASE,
)


@dataclass
class Page:
    url: str
    title: str = ""
    content: str = ""
    error: str = ""
    engine: str = ""

    def as_result(self) -> dict:
        out = {"url": self.url, "title": self.title, "content": self.content, "raw_content": self.content,
               "metadata": {"engine": self.engine} if self.engine else {}}
        if self.error:
            out["error"] = self.error
            out["content"] = out["raw_content"] = ""
        return out


# ---------------------------------------------------------------- pure helpers


def looks_blocked(title: str, text: str) -> str:
    """A reason when the page reads like a bot wall or an error page, else an empty string."""
    m = _WALL_RE.search(f"{title}\n{text[:600]}")
    if not m and len(text) < SHORT_PAGE_CHARS:
        m = _ERROR_RE.search(f"{title}\n{text[:300]}")
    if not m:
        return ""
    return f"error or block page ({m.group(0)!r} in {'title' if m.group(0).lower() in title.lower() else 'text'})"


def strip_links(markdown: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown)  # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> their text
    text = re.sub(r"<https?://[^>]+>", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _value_keys(text: str) -> set[tuple[str, str]]:
    """Values with a unit, and bare numbers of 100 or more that are not years (copyright lines)."""
    keys = set()
    for occ in values.index_page("", text):
        numeric = [float(v) for v in occ.values if re.fullmatch(r"\d+(?:\.\d+)?", v)]  # versions excluded
        if occ.unit or any(n >= 100 and not (1900 <= n < 2100 and n.is_integer()) for n in numeric):
            keys.update((v, occ.unit) for v in occ.values)
    return keys


def _has_label(line: str) -> bool:
    """True when a line names what its values are, unlike benchmark rows such as "117.5 1%"."""
    words = re.findall(r"[^\W\d_]{3,}", line.lower())
    return any(w not in values.UNIT_SPELLINGS for w in words)


def complement(main_text: str, browser_md: str) -> str:
    """Lines of the browser text that hold values the main text lacks, with their headings."""
    known = _value_keys(main_text)
    out: list[str] = []
    heading = ""
    size = 0
    for line in strip_links(browser_md).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            heading = stripped
            continue
        new = _value_keys(stripped) - known
        if not new or not _has_label(stripped):
            continue
        if heading:
            out.append(heading)
            size += len(heading) + 1
            heading = ""
        out.append(stripped)
        size += len(stripped) + 1
        known |= new
        if size > MAX_COMPLEMENT_CHARS:
            break
    return "\n".join(out)


def merge(main_text: str, browser_md: str) -> tuple[str, str]:
    """(content, engine) from trafilatura's text and Crawl4AI's markdown."""
    browser_text = strip_links(browser_md) if browser_md else ""
    if len(main_text.strip()) < 300 and browser_text:
        return browser_text[:MAX_CONTENT_CHARS], "crawl4ai"
    extra = complement(main_text, browser_md) if browser_md else ""
    if extra:
        return f"{main_text}\n\n## More values from this page (browser view)\n{extra}"[:MAX_CONTENT_CHARS], "trafilatura+crawl4ai"
    return main_text[:MAX_CONTENT_CHARS], "trafilatura"


PDF_TIMEOUT = 60
PDF_MEMORY_LIMIT = 1024 * 1024 * 1024  # POSIX only: Windows has no per-process limit to set
PDF_READER = Path(__file__).with_name("pdf_reader.py")


def _limit_memory() -> None:  # runs in the child, before pypdf starts
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (PDF_MEMORY_LIMIT, PDF_MEMORY_LIMIT))


async def pdf_text_isolated(data: bytes) -> str:
    """Text of a PDF, read by pdf_reader.py in a child process stopped after PDF_TIMEOUT seconds
    (and, on POSIX, capped in memory).

    pypdf keeps getting fixes for crafted PDFs that loop forever or exhaust memory, and web PDFs come
    from anywhere: a bad one must not hang or bloat Hermes. Raises RuntimeError on failure or timeout.
    """
    kwargs = {} if os.name == "nt" else {"preexec_fn": _limit_memory}
    # Hermes runs a base interpreter and adds its package environment to sys.path at startup, so
    # the child gets the parent's import path explicitly (and no user site-packages: -s).
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p and os.path.isdir(p)),
           "PYTHONIOENCODING": "utf-8"}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-s", str(PDF_READER), str(MAX_CONTENT_CHARS),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=env, **kwargs,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(data), PDF_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"PDF reading stopped after {PDF_TIMEOUT}s") from None
    if proc.returncode != 0:
        last = (err.decode("utf-8", "replace").strip().splitlines() or ["no output"])[-1]
        raise RuntimeError(last[:200])
    return json.loads(out.decode("utf-8"))["text"]


def html_text(html: str, url: str) -> tuple[str, str]:
    import trafilatura

    text = trafilatura.extract(html, url=url, include_tables=True, include_comments=False) or ""
    meta = trafilatura.extract_metadata(html, default_url=url)
    title = (meta.title if meta and meta.title else "") or ""
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return title, text


# ---------------------------------------------------------------- Crawl4AI side environment


def crawl4ai_python() -> Path | None:
    """The isolated environment's interpreter, without installing anything."""
    try:
        from pm import environment_python
        return environment_python(CRAWL4AI_ENV)
    except Exception:  # noqa: BLE001 - Hermes without pm, or a broken selection: run without it
        return None


async def browser_view(url: str, slots: asyncio.Semaphore | None = None) -> dict:
    """Crawl4AI result for one URL: {success, status, markdown, title, error}."""
    # slots: created per read_pages call, inside its event loop. An asyncio.Semaphore is bound to
    # the loop it first runs in, and Hermes may call the provider from different loops.
    if slots is None:
        return await _browser_view(url)
    async with slots:
        return await _browser_view(url)


async def _browser_view(url: str) -> dict:
    python = crawl4ai_python()
    if python is None:
        return {"success": False, "error": "crawl4ai not installed"}
    env = {**os.environ, "CRAWL4AI_NO_CLOUD_NOTICE": "1", "PYTHONIOENCODING": "utf-8"}
    proc = await asyncio.create_subprocess_exec(
        str(python), "-I", str(RUNNER), url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), BROWSER_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return {"success": False, "error": f"browser timed out after {BROWSER_TIMEOUT}s"}
    lines = [ln for ln in out.decode("utf-8", "replace").splitlines() if ln.startswith("{")]
    if not lines:
        return {"success": False, "error": (err.decode("utf-8", "replace").strip().splitlines() or ["no output"])[-1][:300]}
    return json.loads(lines[-1])


# ---------------------------------------------------------------- one URL


async def _download(client, url: str):
    async with client.stream("GET", url) as response:
        chunks, size = [], 0
        limit = MAX_PDF_BYTES
        async for chunk in response.aiter_bytes():
            chunks.append(chunk)
            size += len(chunk)
            if size > limit:
                break
        return response, b"".join(chunks), size > limit


def _origin(status: int, reason: str) -> str:
    """A page-level failure in Hermes's origin wording ("HTTP <code> from origin: ...").

    The page answered, but with nothing usable. Hermes does not hand such a page to its keyless
    rescue, which would fetch it again through an outside service and can return the same wall
    as content.
    """
    return f"HTTP {status or 200} from origin: {reason}"[:300]


async def read_page(client, url: str, slots: asyncio.Semaphore | None = None) -> Page:
    try:
        return await _read_page(client, url, slots)
    except Exception as exc:  # noqa: BLE001 - one bad page never fails the whole call
        logger.warning("grounded-web: reading %s failed", url, exc_info=True)
        return Page(url, error=f"could not read the page: {exc.__class__.__name__}: {exc}"[:300])


async def _read_page(client, url: str, slots: asyncio.Semaphore | None = None) -> Page:
    browser = asyncio.create_task(browser_view(url, slots)) if not url.lower().split("?")[0].endswith(".pdf") else None
    try:
        response, body, too_big = await _download(client, url)
        status, ctype = response.status_code, response.headers.get("content-type", "").lower()
    except Exception as exc:  # noqa: BLE001 - network errors become the page's error
        status, ctype, body, too_big = 0, "", b"", False
        fetch_error = f"could not download: {exc.__class__.__name__}: {exc}"[:300]
    else:
        fetch_error = f"HTTP {status} from origin" if status >= 400 else ""  # Hermes wording: no keyless rescue

    if not fetch_error and ("pdf" in ctype or body[:5] == b"%PDF-"):
        if browser:
            browser.cancel()
        if too_big:
            return Page(url, error=_origin(status, f"PDF larger than {MAX_PDF_BYTES // 2**20} MB"))
        try:
            text = await pdf_text_isolated(body)
        except Exception as exc:  # noqa: BLE001
            return Page(url, error=_origin(status, f"unreadable PDF: {exc}"))
        return Page(url, url.rsplit("/", 1)[-1], text, "" if text else _origin(status, "PDF has no text layer (scanned?)"), "pdf")

    title, main = "", ""
    if not fetch_error:
        html = body[:MAX_HTML_BYTES].decode(response.encoding or "utf-8", "replace")
        title, main = await asyncio.to_thread(html_text, html, url)

    view = await browser if browser else {"success": False}
    view_ok = view.get("success") and int(view.get("status") or 200) < 400
    if fetch_error and not view_ok:
        return Page(url, error=fetch_error)  # 404, 410, 5xx...: the browser saw no better
    browser_md = view.get("markdown", "") if view_ok else ""
    view_title = (view.get("title") or "") if view_ok else ""
    # Judge each view on its own: a bot wall in one must not pass by riding on the other's text.
    blocked = ""
    if main and (reason := looks_blocked(title, main)):
        main, blocked = "", reason
    if browser_md and (reason := looks_blocked(view_title, strip_links(browser_md))):
        browser_md, blocked = "", reason
    content, engine = merge(main, browser_md)
    title = title or view_title
    if not content.strip():
        return Page(url, title, error=_origin(status, blocked or "no readable text on the page"))
    return Page(url, title, content, engine=engine)


async def read_pages(urls: list[str]) -> list[Page]:
    import httpx

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8,fr;q=0.6"}
    async with httpx.AsyncClient(follow_redirects=True, timeout=FETCH_TIMEOUT, headers=headers) as client:
        slots = asyncio.Semaphore(BROWSERS_AT_ONCE)
        return list(await asyncio.gather(*(read_page(client, u, slots) for u in urls)))


if __name__ == "__main__" and len(sys.argv) > 1:  # manual check: python -m ... URL
    for p in asyncio.run(read_pages(sys.argv[1:])):
        print(json.dumps(p.as_result(), ensure_ascii=False)[:2000])
