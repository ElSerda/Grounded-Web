"""`hermes grounded-web status` and `hermes grounded-web setup`.

setup walks through what grounded-web needs and writes the Hermes config:
  1. a search backend: SearXNG (your instance) or DuckDuckGo (built into Hermes, no key);
  2. web_extract on grounded-web;
  3. optional Crawl4AI, in its own environment, with a headless Chromium (about 300 MB);
  4. auto-loading the bundled research skill;
  5. a live test: one real page, one 404.
Every step is shown before it runs. Nothing is installed without a yes, or the matching flag.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import stat
import subprocess
import sys

from . import compat, extract

CRAWL4AI_REQUIREMENT = "crawl4ai>=0.9.5,<0.10"
TEST_PAGE = "https://www.iana.org/help/example-domains"
SEARXNG_GUIDE = "https://hermes-agent.nousresearch.com/docs/user-guide/features/web-search"
TEST_MISSING = "https://www.iana.org/grounded-web-test-page-that-does-not-exist"


# ---------------------------------------------------------------- output, in Hermes's own style


def _hermes_out(name: str):
    """Hermes's setup output helper `name`, or None when this Hermes does not have it."""
    try:
        if name == "print_header":
            from hermes_cli.setup import print_header as fn
        else:
            import hermes_cli.cli_output as out
            fn = getattr(out, name)
        return fn
    except (ImportError, AttributeError):
        return None


def header(text: str) -> None:
    fn = _hermes_out("print_header")
    fn(text) if fn else print(f"\n== {text}")


def info(text: str) -> None:
    fn = _hermes_out("print_info")
    fn(text) if fn else print(f"  {text}")


def ok(text: str) -> None:
    fn = _hermes_out("print_success")
    fn(text) if fn else print(f"OK {text}")


def warn(text: str) -> None:
    fn = _hermes_out("print_warning")
    fn(text) if fn else print(f"!  {text}")


def error(text: str) -> None:
    fn = _hermes_out("print_error")
    fn(text) if fn else print(f"X  {text}")


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


def print_state(s: dict, title: str = "grounded-web status") -> None:
    header(title)
    search = s["search_backend"]
    if search == "(auto)":
        warn("Search             (auto): Hermes picks a backend from your environment variables")
    else:
        ok(f"Search             {search}")
    if search == "searxng" or s["searxng_url"]:
        (ok if s["searxng_url"] else error)(f"SEARXNG_URL        {s['searxng_url'] or '(not set)'}")
    if s["extract_backend"] == "grounded-web":
        ok("Page reading       grounded-web")
    else:
        error(f"Page reading       {s['extract_backend']} (grounded-web is not selected)")
    deps = s["trafilatura"] and s["pypdf"]
    (ok if deps else error)("trafilatura, pypdf " + ("installed" if deps else "missing: run `hermes plugins enable grounded-web`"))
    if search == "ddgs":
        (ok if s["ddgs"] else error)("DuckDuckGo (ddgs)  " + ("installed" if s["ddgs"] else "missing"))
    if s["crawl4ai_python"]:
        ok("Crawl4AI           installed")
        (ok if s["browser"] else error)("Headless Chromium  " + ("installed" if s["browser"] else "missing: run setup again"))
    else:
        warn("Crawl4AI           not installed (pages are read with trafilatura only)")
    others = compat.other_reply_rewriters("grounded-web")
    if others:
        verb = "also rewrites" if len(others) == 1 else "also rewrite"
        warn(f"Reply rewriters    {', '.join(others)} {verb} replies, and Hermes keeps only one rewrite.")
        info("grounded-web leaves the reply to them (show_sources: auto). Set it to `always` to show its")
        info("footer anyway, or turn the other plugin off: `hermes plugins disable <name>`.")


# ---------------------------------------------------------------- asking


def _ask(question: str, default: str, interactive: bool) -> str:
    """A typed answer, with Hermes's own prompt style when it is available."""
    if not interactive:
        return default
    try:
        from hermes_cli.setup import prompt
    except ImportError:
        return input(f"{question} [{default}] ").strip() or default
    return prompt(question.strip(), default) or default


def _choose(title: str, options: list[tuple[str, str]], default: str, interactive: bool, description: str = "") -> str:
    """One option key, picked with Hermes's own menu (arrows, Enter, Esc keeps the default).

    Hermes falls back to a numbered list by itself when the terminal cannot draw the menu. If the
    menu module is missing (a future Hermes), a plain typed answer is used instead.
    """
    keys = [k for k, _ in options]
    selected = keys.index(default) if default in keys else 0
    if not interactive:
        return keys[selected]
    try:
        from hermes_cli.curses_ui import curses_radiolist
    except ImportError:
        print(f"   {title}")
        for key, label in options:
            print(f"     {key:8} {label}")
        answer = _ask("   Choice?", keys[selected], interactive).lower()
        return answer if answer in keys else keys[selected]
    labels = [f"{label}" for _, label in options]
    index = curses_radiolist(title, labels, selected=selected, cancel_returns=selected,
                             description=description or None)
    return keys[index if 0 <= index < len(keys) else selected]


def _confirm(question: str, default: bool, interactive: bool, description: str = "") -> bool:
    options = [("yes", "Yes"), ("no", "No")]
    return _choose(question.strip(), options, "yes" if default else "no", interactive, description) == "yes"


# ---------------------------------------------------------------- what setup replaced, for uninstall

PLUGIN_NAME = "grounded-web"
RESTORED_KEYS = ("web.search_backend", "web.extract_backend")


def _data_dir():
    try:
        from plugins.plugin_storage import plugin_data_dir
        return plugin_data_dir(PLUGIN_NAME)
    except Exception:  # noqa: BLE001
        return None


def _previous() -> dict:
    d = _data_dir()
    try:
        return json.loads((d / "previous.json").read_text(encoding="utf-8")) if d else {}
    except (OSError, ValueError):
        return {}


def _config_value(key: str):
    node = _config()
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set(key: str, value: str) -> None:
    """Write a Hermes setting; the first time setup changes a web backend, keep the old value."""
    from hermes_cli.config import set_config_value
    if key in RESTORED_KEYS:
        previous = _previous()
        if key not in previous and (d := _data_dir()) is not None:
            previous[key] = _config_value(key)
            (d / "previous.json").write_text(json.dumps(previous, indent=1), encoding="utf-8")
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
    header("1. Search backend")
    options = [
        ("ddgs", "DuckDuckGo: built into Hermes, no key, no server"),
        ("searxng", "SearXNG: your own instance (self-hosted, many engines)"),
        ("keep", f"Keep the current one ({s['search_backend']})"),
    ]
    if args.search:
        choice = args.search
    else:
        default = "searxng" if s["searxng_url"] else "ddgs"
        choice = _choose("Search backend for web_search", options, default, interactive,
                         "grounded-web reads pages; search comes from one of these.")
    info(dict(options)[choice])
    if choice == "keep":
        return
    if choice == "searxng":
        url = args.searxng_url or _ask("   SearXNG URL?", s["searxng_url"] or "http://localhost:8080", interactive)
        while (problem := _check_searxng(url)):
            error(problem)
            info(f"No SearXNG yet? Hermes's guide runs one with Docker: {SEARXNG_GUIDE}")
            # Never leave search unset without saying so: DuckDuckGo is the safe default.
            fallback = "save" if args.searxng_url and not interactive else "ddgs"
            what = _choose("SearXNG is not answering. What now?", [
                ("ddgs", "Use DuckDuckGo instead (works now, no server)"),
                ("retry", "Enter another SearXNG URL"),
                ("save", "Save this URL anyway (start SearXNG later)"),
                ("keep", f"Keep the current search backend ({s['search_backend']})"),
            ], fallback, interactive, problem)
            if what == "retry":
                url = _ask("   SearXNG URL?", url, interactive)
                continue
            if what == "keep":
                warn(f"Search backend unchanged: {s['search_backend']}")
                return
            if what == "ddgs":
                warn("Using DuckDuckGo instead. Run setup again once SearXNG is up.")
                choice = "ddgs"
            break
        else:
            ok("SearXNG answers JSON searches")
        if choice == "searxng":
            from hermes_cli.config import save_env_value
            save_env_value("SEARXNG_URL", url.rstrip("/"))
            _set("web.search_backend", "searxng")
            return
    if choice == "ddgs":
        if not s["ddgs"]:
            info("DuckDuckGo needs Hermes's `ddgs` extra.")
            if not _confirm("Install Hermes's ddgs extra now?", True, interactive,
                            "DuckDuckGo search runs through the ddgs package, which Hermes installs on request."):
                return
            from pm import ensure_import
            ensure_import("ddgs")
        if s["search_backend"] == "ddgs":
            ok("Search backend already ddgs")
        else:
            _set("web.search_backend", "ddgs")
    else:
        warn(f"Unknown choice {choice!r}, search backend unchanged.")


def step_extract(s: dict) -> None:
    header("2. Page reading")
    info("web_extract reads pages and PDFs on this machine with grounded-web.")
    if s["extract_backend"] == "grounded-web":
        ok("Page reading already on grounded-web")
    else:
        _set("web.extract_backend", "grounded-web")


def step_crawl4ai(args, s: dict, interactive: bool) -> None:
    header("3. Crawl4AI (optional)")
    info("Opens each page in a headless browser as well. It recovers values that the main")
    info("text reader drops (spec tables) and pages built by scripts. It lives in its own")
    info("environment, apart from Hermes's packages: about 35 packages and a 280 MB")
    info("headless Chromium in Playwright's browser folder.")
    if s["crawl4ai_python"] and s["browser"]:
        ok("Crawl4AI already installed")
        return
    wanted = args.crawl4ai if args.crawl4ai is not None else _confirm(
        "Install Crawl4AI?", True, interactive,
        "Crawl4AI: about 35 packages in their own environment, plus a 280 MB headless Chromium.\n"
        "It recovers spec tables and script-built pages that the main text reader misses.")
    if not wanted:
        warn("Skipped. Pages are read with trafilatura alone; run setup again to add it.")
        return
    from pm import ensure_environment
    info("Preparing the environment (a few minutes the first time)...")
    python = ensure_environment(extract.CRAWL4AI_ENV, [CRAWL4AI_REQUIREMENT], explicit=True)
    info("Downloading the headless Chromium...")
    done = subprocess.run([str(python), "-m", "playwright", "install", "--only-shell", "chromium"])
    if done.returncode != 0:
        error("The browser download failed; Crawl4AI stays off until it succeeds.")
    else:
        ok("Crawl4AI installed")


SKILL = "grounded-web:web-research"


def step_skill(args, interactive: bool) -> None:
    header("4. Research skill")
    info(f"{SKILL} tells the model to open pages instead of answering from search snippets,")
    info("one URL per web_extract call. Auto-loading puts it in every new session (about 600 tokens).")
    current = ((_config().get("skills") or {}).get("auto_load")) or []
    if not isinstance(current, list):
        current = []
    if SKILL in current:
        ok("Research skill already auto-loaded")
        return
    wanted = args.skill if args.skill is not None else _confirm(
        f"Auto-load {SKILL}?", True, interactive,
        "The skill makes the model open pages instead of answering from search snippets.\n"
        "It is added to every new session (about 600 tokens).")
    if not wanted:
        warn(f"Skipped. Load it by hand with /skill {SKILL}.")
        return
    import json
    _set("skills.auto_load", json.dumps([*current, SKILL]))


def step_test() -> bool:
    header("5. Test")
    page, missing = asyncio.run(extract.read_pages([TEST_PAGE, TEST_MISSING]))
    good = bool(page.content) and not page.error
    if good:
        ok(f"Read {TEST_PAGE}: {len(page.content)} characters via {page.engine}")
    else:
        error(f"Could not read {TEST_PAGE}: {page.error}")
    caught = bool(missing.error)
    if caught:
        ok(f"A missing page is reported as an error ({missing.error})")
    else:
        error("A missing page was NOT reported as an error")
    return good and caught


# ---------------------------------------------------------------- uninstall


def _rmtree(path) -> None:
    def clear_readonly(func, target, _exc):
        import os
        os.chmod(target, stat.S_IWRITE)
        func(target)
    shutil.rmtree(path, onexc=clear_readonly) if sys.version_info >= (3, 12) else shutil.rmtree(path, onerror=clear_readonly)


def _browser_dirs_in_use_elsewhere(own_package) -> set[str]:
    """Browser folder names (e.g. chromium_headless_shell-1248) that other registered Playwright
    installs on this machine need, read from each one's browsers.json."""
    from pathlib import Path
    import os
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "")
    if not root.name:
        local = os.environ.get("LOCALAPPDATA")
        root = Path(local) / "ms-playwright" if local else Path.home() / ".cache" / "ms-playwright"
        if sys.platform == "darwin":
            root = Path.home() / "Library" / "Caches" / "ms-playwright"
    needed: set[str] = set()
    for link in (root / ".links").glob("*") if (root / ".links").is_dir() else []:
        try:
            package = Path(link.read_text(encoding="utf-8").strip())
        except OSError:
            continue
        if own_package and package.resolve() == own_package.resolve():
            continue
        try:
            data = json.loads((package / "browsers.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # that install is gone: its browsers are not ours to judge
        for b in data.get("browsers", []):
            needed.add(f"{str(b.get('name', '')).replace('-', '_')}-{b.get('revision', '')}")
    return needed


def _remove_own_browsers(python) -> list[str]:
    """Delete the browser folders Crawl4AI's Playwright installed, unless another install needs them."""
    from pathlib import Path
    out = subprocess.run([str(python), "-m", "playwright", "install", "--only-shell", "--dry-run", "chromium"],
                         capture_output=True, text=True, timeout=60)
    ours = [Path(line.split(":", 1)[1].strip()) for line in out.stdout.splitlines() if "Install location" in line]
    try:
        package = Path(subprocess.run([str(python), "-c", "import playwright, pathlib; print(pathlib.Path(playwright.__file__).parent / 'driver' / 'package')"],
                                      capture_output=True, text=True, timeout=60).stdout.strip())
    except Exception:  # noqa: BLE001
        package = None
    elsewhere = _browser_dirs_in_use_elsewhere(package)
    removed = []
    if package is not None and ours:  # drop this install's registration in Playwright's .links
        for link in (ours[0].parent / ".links").glob("*"):
            try:
                if Path(link.read_text(encoding="utf-8").strip()).resolve() == package.resolve():
                    link.unlink()
            except OSError:
                continue
    for folder in ours:
        if folder.exists() and folder.name not in elsewhere:
            _rmtree(folder)
            removed.append(folder.name)
        elif folder.exists():
            info(f"Kept {folder.name}: another Playwright install on this machine uses it.")
    return removed


def uninstall(interactive: bool) -> int:
    """Undo what setup did, so `hermes plugins remove grounded-web` leaves nothing behind."""
    from hermes_cli.config import set_config_value, unset_config_value

    header("Remove grounded-web's settings and downloads")
    info("Run this before `hermes plugins remove grounded-web`. It restores the web backends that")
    info("setup replaced, removes the research skill from auto-load, and deletes Crawl4AI's")
    info("environment and its headless Chromium.")
    if not _confirm("Remove grounded-web's settings and downloads?", True, interactive,
                    "Restores web backends, drops the skill from auto-load, deletes Crawl4AI and its Chromium."):
        warn("Nothing changed.")
        return 1
    previous = _previous()
    for key in RESTORED_KEYS:
        current = _config_value(key)
        if key in previous:
            old = previous[key]
            if old in (None, ""):
                unset_config_value(key)
            elif old != current:
                set_config_value(key, str(old))
            ok(f"{key} restored to {old or '(not set)'}")
        elif current == PLUGIN_NAME:
            unset_config_value(key)  # set by hand: grounded-web will be gone, so do not leave it pointing there
            ok(f"{key} cleared (it pointed at grounded-web)")
    auto = _config_value("skills.auto_load")
    if isinstance(auto, list) and SKILL in auto:
        set_config_value("skills.auto_load", json.dumps([name for name in auto if name != SKILL]))
    python = extract.crawl4ai_python()
    if python is not None:
        removed = _remove_own_browsers(python)
        if removed:
            ok(f"Browser files removed: {', '.join(removed)}")
    try:
        from hermes_constants import get_hermes_home
        env_dir = get_hermes_home() / "environments" / extract.CRAWL4AI_ENV
    except Exception:  # noqa: BLE001
        env_dir = None
    if env_dir is not None and env_dir.exists():
        _rmtree(env_dir)
        ok(f"Crawl4AI environment deleted ({env_dir})")
    d = _data_dir()
    if d is not None and d.exists():
        _rmtree(d)
    if _secret("SEARXNG_URL"):
        info("SEARXNG_URL stays in Hermes's .env; Hermes's own SearXNG backend uses it too.")
    print()
    info("Now run `hermes plugins remove grounded-web`, then restart Hermes.")
    return 0


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
    sk = setup.add_mutually_exclusive_group()
    sk.add_argument("--skill", dest="skill", action="store_true", default=None, help="Auto-load the research skill")
    sk.add_argument("--no-skill", dest="skill", action="store_false", help="Do not auto-load the research skill")
    setup.add_argument("--yes", action="store_true", help="Accept the defaults without asking")
    rm = subs.add_parser("uninstall", help="Undo setup before `hermes plugins remove grounded-web`")
    rm.add_argument("--yes", action="store_true", help="Do not ask for confirmation")
    parser.set_defaults(func=handle)


def handle(args) -> int:
    command = getattr(args, "grounded_web_command", None)
    if command == "status":
        print_state(state())
        return 0
    if command == "uninstall":
        if not args.yes and not sys.stdin.isatty():
            error("No terminal to confirm in: run `hermes grounded-web uninstall --yes`.")
            return 1
        return uninstall(not args.yes)
    if command != "setup":
        print("Usage: hermes grounded-web <status|setup|uninstall>")
        return 1
    interactive = not args.yes
    if interactive and not sys.stdin.isatty():
        error("No terminal to ask questions in: run with --yes, plus --search / --crawl4ai / --skill to choose.")
        return 1
    s = state()
    print_state(s)
    step_search(args, s, interactive)
    step_extract(s)
    step_crawl4ai(args, s, interactive)
    step_skill(args, interactive)
    passed = step_test()
    print_state(state(), "Saved settings")  # what was really saved, so a skipped step shows here
    print()
    info("Restart Hermes (or `hermes gateway restart`) so running sessions pick up the changes.")
    return 0 if passed else 1


def register(ctx) -> None:
    ctx.register_cli_command(
        name="grounded-web",
        help="Set up and check grounded-web (search, page reading, Crawl4AI)",
        setup_fn=_setup_parser,
        handler_fn=handle,
    )
