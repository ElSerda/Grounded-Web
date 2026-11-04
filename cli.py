"""`hermes grounded-web status` and `hermes grounded-web setup`.

setup walks through what grounded-web needs and writes the Hermes config:
  1. a search backend: SearXNG (your instance) or DuckDuckGo (built into Hermes, no key);
  2. web_extract on grounded-web;
  3. optional Crawl4AI, in its own environment, with a headless Chromium (about 300 MB);
  4. a live test: one real page, one 404.
Every step is shown before it runs. Nothing is installed without a yes, or the matching flag.
"""

from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys

from . import extract

CRAWL4AI_REQUIREMENT = "crawl4ai>=0.9.5,<0.10"
TEST_PAGE = "https://www.iana.org/help/example-domains"
TEST_MISSING = "https://www.iana.org/grounded-web-test-page-that-does-not-exist"


# ---------------------------------------------------------------- reading the current state


def _config() -> dict:
    try:
        from hermes_cli.config import load_config_readonly
        return load_config_readonly() or {}
    except Exception:  # noqa: BLE001
        return {}


def _secret(name: str) -> str:
    try:
        from agent.secret_scope import get_secret
        return (get_secret(name) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _has(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def _browser_ready(python) -> bool:
    """True when Playwright's headless shell for this Crawl4AI is already downloaded."""
    if python is None:
        return False
    out = subprocess.run([str(python), "-m", "playwright", "install", "--only-shell", "--dry-run", "chromium"],
                         capture_output=True, text=True, timeout=60)
    from pathlib import Path
    paths = [line.split(":", 1)[1].strip() for line in out.stdout.splitlines() if "Install location" in line]
    shell = [p for p in paths if "headless_shell" in p]
    return bool(shell) and all(Path(p).exists() for p in shell)


def state() -> dict:
    web = (_config().get("web") or {})
    c4ai = extract.crawl4ai_python()
    return {
        "search_backend": web.get("search_backend") or web.get("backend") or "(auto)",
        "extract_backend": web.get("extract_backend") or web.get("backend") or "(auto)",
        "searxng_url": _secret("SEARXNG_URL"),
        "trafilatura": _has("trafilatura"),
        "pypdf": _has("pypdf"),
        "ddgs": _has("ddgs"),
        "crawl4ai_python": c4ai,
        "browser": _browser_ready(c4ai),
    }


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def print_state(s: dict) -> None:
    print("grounded-web status")
    print(f"  search backend      {s['search_backend']}")
    print(f"  extract backend     {s['extract_backend']}" + ("" if s["extract_backend"] == "grounded-web" else "   (grounded-web not selected)"))
    print(f"  SEARXNG_URL         {s['searxng_url'] or '(not set)'}")
    print(f"  trafilatura, pypdf  {_yes(s['trafilatura'])}, {_yes(s['pypdf'])}")
    print(f"  DuckDuckGo (ddgs)   {_yes(s['ddgs'])}")
    print(f"  Crawl4AI            {s['crawl4ai_python'] or 'not installed (pages are read with trafilatura only)'}")
    if s["crawl4ai_python"]:
        print(f"  headless Chromium   {_yes(s['browser'])}")


# ---------------------------------------------------------------- asking


def _ask(question: str, default: str, interactive: bool) -> str:
    if not interactive:
        return default
    answer = input(f"{question} [{default}] ").strip()
    return answer or default


def _confirm(question: str, default: bool, interactive: bool) -> bool:
    answer = _ask(f"{question} (y/n)", "y" if default else "n", interactive).lower()
    return answer.startswith(("y", "o"))  # yes / oui


def _set(key: str, value: str) -> None:
    from hermes_cli.config import set_config_value
    set_config_value(key, value)


# ---------------------------------------------------------------- steps


def _check_searxng(url: str) -> str:
    """An empty string when the instance answers JSON searches, else what is wrong."""
    import httpx
    try:
        r = httpx.get(f"{url.rstrip('/')}/search", params={"q": "grounded web test", "format": "json"}, timeout=20)
    except httpx.HTTPError as exc:
        return f"cannot reach {url}: {exc}"
    if r.status_code == 403:
        return "SearXNG refuses JSON: add `json` to `search.formats` in its settings.yml, then restart it"
    if r.status_code >= 400:
        return f"SearXNG answered HTTP {r.status_code}"
    try:
        n = len(r.json().get("results", []))
    except ValueError:
        return "SearXNG did not answer JSON (is this the instance URL?)"
    return "" if n else "SearXNG answered, but with 0 results (are its engines enabled?)"


def step_search(args, s: dict, interactive: bool) -> None:
    print("\n1. Search backend")
    print("   searxng  your SearXNG instance (self-hosted, many engines)")
    print("   ddgs     DuckDuckGo, built into Hermes, no key, no server")
    print("   keep     leave it as it is")
    default = args.search or ("searxng" if s["searxng_url"] else "ddgs")
    choice = _ask("   Which one?", default, interactive).lower()
    if choice == "keep":
        return
    if choice == "searxng":
        url = args.searxng_url or _ask("   SearXNG URL?", s["searxng_url"] or "http://localhost:8080", interactive)
        problem = _check_searxng(url)
        if problem:
            print(f"   ! {problem}")
            if not _confirm("   Save it anyway?", False, interactive):
                return
        else:
            print("   SearXNG answers JSON searches.")
        from hermes_cli.config import save_env_value
        save_env_value("SEARXNG_URL", url.rstrip("/"))
        _set("web.search_backend", "searxng")
    elif choice == "ddgs":
        if not s["ddgs"]:
            print("   DuckDuckGo needs Hermes's `ddgs` extra.")
            if not _confirm("   Install it now?", True, interactive):
                return
            from pm import ensure_import
            ensure_import("ddgs")
        _set("web.search_backend", "ddgs")
    else:
        print(f"   Unknown choice {choice!r}, search backend unchanged.")


def step_extract(s: dict) -> None:
    print("\n2. Page reading")
    if s["extract_backend"] != "grounded-web":
        _set("web.extract_backend", "grounded-web")
    print("   web_extract reads pages and PDFs on this machine with grounded-web.")


def step_crawl4ai(args, s: dict, interactive: bool) -> None:
    print("\n3. Crawl4AI (optional)")
    print("   Opens each page in a headless browser as well. It recovers values that the main")
    print("   text reader drops (spec tables) and pages built by scripts. It lives in its own")
    print("   environment, apart from Hermes's packages: about 35 packages and a 280 MB")
    print("   headless Chromium in Playwright's browser folder.")
    if s["crawl4ai_python"] and s["browser"]:
        print("   Already installed.")
        return
    wanted = args.crawl4ai if args.crawl4ai is not None else _confirm("   Install it?", True, interactive)
    if not wanted:
        print("   Skipped. Pages are read with trafilatura alone; run setup again to add it.")
        return
    from pm import ensure_environment
    print("   Preparing the environment (a few minutes the first time)...")
    python = ensure_environment(extract.CRAWL4AI_ENV, [CRAWL4AI_REQUIREMENT], explicit=True)
    print("   Downloading the headless Chromium...")
    done = subprocess.run([str(python), "-m", "playwright", "install", "--only-shell", "chromium"])
    if done.returncode != 0:
        print("   ! The browser download failed; Crawl4AI stays off until it succeeds.")


def step_test() -> bool:
    print("\n4. Test")
    pages = asyncio.run(extract.read_pages([TEST_PAGE, TEST_MISSING]))
    ok, missing = pages
    good = bool(ok.content) and not ok.error
    print(f"   {TEST_PAGE}: " + (f"{len(ok.content)} characters via {ok.engine}" if good else f"FAILED: {ok.error}"))
    caught = bool(missing.error)
    print(f"   missing page: " + (f"reported as an error ({missing.error})" if caught else "NOT reported as an error"))
    return good and caught


# ---------------------------------------------------------------- entry points


def _setup_parser(parser) -> None:
    subs = parser.add_subparsers(dest="grounded_web_command")
    subs.add_parser("status", help="Show what grounded-web uses")
    setup = subs.add_parser("setup", help="Configure search, page reading and Crawl4AI")
    setup.add_argument("--search", choices=["searxng", "ddgs", "keep"], help="Search backend to select")
    setup.add_argument("--searxng-url", help="SearXNG instance URL (with --search searxng)")
    c4 = setup.add_mutually_exclusive_group()
    c4.add_argument("--crawl4ai", dest="crawl4ai", action="store_true", default=None, help="Install Crawl4AI")
    c4.add_argument("--no-crawl4ai", dest="crawl4ai", action="store_false", help="Do not install Crawl4AI")
    setup.add_argument("--yes", action="store_true", help="Accept the defaults without asking")
    parser.set_defaults(func=handle)


def handle(args) -> int:
    command = getattr(args, "grounded_web_command", None)
    if command == "status":
        print_state(state())
        return 0
    if command != "setup":
        print("Usage: hermes grounded-web <status|setup>")
        return 1
    interactive = not args.yes
    if interactive and not sys.stdin.isatty():
        print("No terminal to ask questions in: run with --yes, plus --search / --crawl4ai to choose.")
        return 1
    s = state()
    print_state(s)
    step_search(args, s, interactive)
    step_extract(s)
    step_crawl4ai(args, s, interactive)
    passed = step_test()
    print("\nRestart Hermes (or `hermes gateway restart`) so running sessions pick up the changes.")
    return 0 if passed else 1


def register(ctx) -> None:
    ctx.register_cli_command(
        name="grounded-web",
        help="Set up and check grounded-web (search, page reading, Crawl4AI)",
        setup_fn=_setup_parser,
        handler_fn=handle,
    )
