# grounded-web

A Hermes Agent plugin for web answers you can check.

- **Reads pages and PDFs on your machine** for `web_extract`: no API key, no extraction service.
- **Lists the pages the answer really used**, under the answer.
- **Checks the answer's values against those pages**: every number with a unit, price, version and large number in the answer must appear in an opened page. When two pages give different values for the same thing, it says so.

The check is plain code. It costs no tokens and makes no model call.

```
Résolution max : 4K @ 480 Hz ou 8K @ 165 Hz (avec DSC)
...

Sources (pages ouvertes) :
- https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5080/
- https://www.notebookcheck.net/Nvidia-GeForce-RTX-5080-Benchmarks-and-Specs.935679.0.html

Vérification : 31 valeurs sur 32 retrouvées dans ces pages.
Absent des pages ouvertes : 30 Gbps
Les pages divergent après « or 8k at » : 165Hz (nvidia.com) / 120Hz (notebookcheck.net)
```

The footer follows the language of the answer (English or French).

## Why

A web answer can go wrong in three places, and the model cannot see any of them.

1. **The page reader drops the data.** Main-text extractors discard what looks like page furniture. On NVIDIA's RTX 5080 page, trafilatura keeps 3,400 characters of marketing text and drops the whole spec table, so the model never sees "8K at 165Hz".
2. **A source is wrong.** Notebookcheck's page for the same card says "8K at 120Hz". A model that reads only that page repeats it faithfully.
3. **The model fills gaps from memory.** In tests, local models wrote core counts, versions and power figures that were on none of the pages they had opened.

grounded-web fixes the first and makes the other two visible.

## How a page is read

1. Download it. An HTTP error (404, 410, 5xx) is reported as an error, unless a browser can still open the page.
2. PDF: text with pypdf. HTML: main text with trafilatura.
3. With Crawl4AI installed, the same page is also opened in a headless browser. Lines of the browser view that hold values missing from the main text, such as spec table rows, are appended under "More values from this page". Pages that trafilatura cannot read, because scripts build them, use the browser view instead.
4. Bot walls ("Just a moment...", "Automated bot check") and short error pages that answer HTTP 200 are reported as errors. The model never receives them as content.

Each page is capped at 30,000 characters.

## How the check works

After each turn, the plugin compares the final answer with the text of every page `web_extract` returned in that turn.

- Spellings are matched: `1 344 Go/s` = `1,344 GB/sec`, `65,3 TFLOPS` = `65.3 TFLOPS¹`, and a unit in a table header (`| AI TOPS | 2064 |`) counts.
- Small bare numbers (generations, counts), product codes (`GB203-400-A1`), links and any source list the model wrote itself are skipped.
- A conflict is two pages giving different values with the same unit after the same words.

It does not decide which source is right, and it does not check claims without numbers.

## Install

Requires Hermes Agent 0.22.6 or later.

```
hermes plugins install ElSerda/Beta-Grounded-Web
hermes grounded-web setup
```

Hermes asks before installing the Python dependencies (trafilatura, pypdf). Then `setup`:

1. chooses a search backend: your **SearXNG** instance (it checks that JSON output is enabled) or **DuckDuckGo** (`ddgs`, built into Hermes, no key);
2. sets `web.extract_backend: grounded-web`;
3. offers **Crawl4AI**, which is optional;
4. offers to auto-load the bundled skill `grounded-web:web-research` (it tells the model to open pages instead of answering from snippets, one URL per call; about 600 tokens per session);
5. tests one real page and one missing page.

Non-interactive: `hermes grounded-web setup --yes --search ddgs --crawl4ai --skill`.
Check at any time with `hermes grounded-web status`.

### Crawl4AI

Crawl4AI pulls about 35 packages and a browser, so it is not installed into Hermes's environment. `setup` creates a separate environment with `hermes pm` (`HERMES_HOME/environments/grounded-web-crawl4ai`). It then downloads Playwright's headless Chromium shell (about 280 MB) to Playwright's browser folder (`%LOCALAPPDATA%\ms-playwright` on Windows, `~/.cache/ms-playwright` on Linux, `~/Library/Caches/ms-playwright` on macOS). That folder is outside `HERMES_HOME`: uninstalling Hermes does not remove it.

Without Crawl4AI, pages are read with trafilatura only, and the spec-table problem above remains.

## Settings

Under Settings → Plugins in Hermes Desktop, or `plugins.entries.grounded-web.settings` in `config.yaml`:

| Key | Default | Meaning |
|---|---|---|
| `language` | `auto` | Footer language: `auto`, `en` or `fr` |
| `show_sources` | `true` | List the opened pages |
| `verify` | `true` | Check the answer's values |

Search and page reading are separate settings: grounded-web only reads pages. It works with any search backend.

## What it does, for review

- **Hooks:** `pre_llm_call` (starts a record for the turn), `post_tool_call` (keeps the text of `web_extract` results), `transform_llm_output` (appends the footer; the answer itself is not changed, so a streamed answer is not printed twice).
- **Web provider:** `grounded-web`, extract only.
- **CLI:** `hermes grounded-web status|setup`.
- **Skill:** `grounded-web:web-research`, read-only, loaded only if you auto-load it or call it.
- **Network:** downloads the URLs the agent asks `web_extract` to read, directly from this machine with a desktop browser user agent. `setup` also checks the SearXNG URL you give it and reads two test pages on iana.org. Crawl4AI's browser loads the same URLs and their page assets.
- **Processes:** one Crawl4AI child process per page, at most three at once, each stopped after 60 seconds.
- **Writes:** `web.search_backend`, `web.extract_backend`, `skills.auto_load` and, for SearXNG, `SEARXNG_URL` in `.env`, all through Hermes's own config functions and only during `setup`. Nothing else is stored: page text lives in memory for the current turn only.
- **No telemetry**, no credentials read, no self-update.

## Limits

- The check confirms that a value appears in an opened page. It cannot tell whether that page is right, unless another opened page disagrees.
- Values computed by the model (`30 Gbps` from "30000 MT/s") are reported as missing. That is on purpose: they are not in the sources.
- Pages behind logins or strong bot protection cannot be read; they come back as errors.

## Development

```
python -m venv .venv
.venv/Scripts/python -m pip install pytest      # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m pytest tests
hermes plugins validate .
```

The tests use made-up pages and need no network.

## License

MIT
