# grounded-web

A Hermes Agent plugin for web answers built from pages that were really read.

- **Reads pages and documents on your machine** for `web_extract` (HTML, PDF, Word, PowerPoint, Excel, OpenDocument, EPUB, RTF, CSV): no API key, no extraction service.
- **Reports 404s, error pages and bot walls as errors**, so the model never takes them for content.
- **Lists the pages the answer really used**, under the answer, with clickable links. Pages are taken from the tool results, never from the model's text, so the list cannot name a page that was not read.
- **Pushes the model to open pages** instead of answering from search snippets: a bundled skill and a one-sentence reminder.

A real run, fully local: Gemma 4 E4B in LM Studio, DuckDuckGo search, pages read by grounded-web.

```
> On each Nous Portal plan, how much RAM and disk does the included Hermes Cloud agent get,
  and what does each plan cost?

*   **Free:** $0, pay as you go (No included cloud agent)
*   **Plus:** $20 / month (4 GB RAM, 25 GB disk)
*   **Super:** $100 / month (4 GB RAM, 100 GB disk)
*   **Ultra:** $200 / month (8 GB RAM, 100 GB disk)

Sources (opened pages):
- Hermes Cloud — Always-On AI Agent Hosting: https://portal.nousresearch.com/cloud
- Nous Portal Subscription: Plans, Credits, and Hermes Agent Setup — Agentic Bo...: https://agenticbotsitter.com/guides/nous-portal-subscription-hermes-agent/
```

Links are written out in full rather than as Markdown links: the Hermes CLI prints replies as plain text, where a bare link stays clickable (Ctrl+click in Windows Terminal) and Desktop and chat apps link it too.

The footer is in English or French. By default it follows Hermes's `display.language`, like Hermes's own notices; set `language: answer` to follow the language of the reply instead.

## Why

A web answer can go wrong in three places, and the model cannot see any of them.

1. **The page reader drops the data.** Main-text extractors discard what looks like page furniture. On the Nous Portal home page, trafilatura keeps the text but drops the plan list with each plan's Cloud agent size ("up to 4 GB RAM and 25 GB disk", "up to 8 GB RAM and 100 GB disk"). Without it, the answer above could not be given from that page.
2. **The page is not a page.** A 404, an "access denied" page or a bot wall ("Automated bot check in progress") often answers HTTP 200. Read as content, it gives the model nothing, or worse, a page of the wrong text.
3. **The model answers from snippets or memory.** Small models in particular stop at the search results when a snippet holds a number, or fill gaps from memory. In tests, Qwen3-8B gave `v0.5.2` as the latest llama.cpp release with the releases page open, where no such version appears.

grounded-web fixes the first two, pushes against the third, and shows which pages the answer came from so you can check it yourself.

## How a page is read

1. Download it. An HTTP error (404, 410, 5xx) is reported as an error, unless a browser can still open the page.
2. Documents (PDF, Office, OpenDocument, EPUB, RTF, CSV): Markdown, tables included, with anydoc, the converter Hermes's own `read_file` uses (its `doc-extract` extra, installed by `setup` or on first use). It runs in a separate process stopped after 60 seconds (and, on Linux and macOS, limited to 2 GB of address space and run with 4 threads), so a crafted document cannot hang Hermes or take over the machine. A scanned PDF (page images, no text layer) is read by local OCR when it is installed: RapidOCR, no language model, about 1 second per page; the text comes with a note that it was read by OCR. Without OCR, the error names the scanned pages. HTML: main text with trafilatura.
3. With Crawl4AI installed, the same page is also opened in a headless browser (the Chromium Hermes installs). Lines of the browser view that hold values missing from the main text, such as spec table rows, are appended under "More values from this page". Pages that trafilatura cannot read, because scripts build them, use the browser view instead.
4. Bot walls ("Just a moment...", "Automated bot check") and short error pages that answer HTTP 200 are reported as errors, in Hermes's `HTTP <code> from origin: ...` form. Hermes then does not re-fetch them through its keyless rescue (an outside service that can return the same wall as content), and a wall that another backend returns is never listed as a source.

Each page is capped at 30,000 characters.

## Which pages are listed

Every page `web_extract` returned with real content in this turn. A page opened in an earlier turn of the conversation is added under "Also used, opened earlier in this conversation" when the answer contains one of its values with a unit, a price or a version: an answer may rely on a page read a few turns before. When no page was opened, the footer says that the answer relies on search snippets only.

## Install

Requires Hermes Agent 0.22.6 or later.

```
hermes plugins install ElSerda/Grounded-Web
hermes grounded-web setup
```

Hermes asks before installing the plugin's one Python dependency (trafilatura). Then `setup`:

1. chooses a search backend: your **SearXNG** instance (it checks that JSON output is enabled) or **DuckDuckGo** (`ddgs`, built into Hermes, no key);
2. sets `web.extract_backend: grounded-web`, and installs Hermes's document converter (`doc-extract`) if missing;
3. offers **Crawl4AI**, which is optional;
4. offers **local OCR** for scanned PDFs (RapidOCR), which is optional;
5. offers to auto-load the bundled skill `grounded-web:web-research` (it tells the model to open pages instead of answering from snippets, one URL per call; about 600 tokens per session);
6. tests one real page and one missing page.

Non-interactive: `hermes grounded-web setup --yes --search ddgs --crawl4ai --ocr --skill`.
Check at any time with `hermes grounded-web status`.

### Uninstall

```
hermes grounded-web uninstall
hermes plugins remove grounded-web
```

`uninstall` puts back the web backends `setup` replaced (it records them in `HERMES_HOME/plugin-data/grounded-web`), removes the skill from `skills.auto_load`, and deletes the Crawl4AI and OCR environments. Hermes's Chromium stays: it belongs to Hermes. `hermes plugins remove` alone would leave `web.extract_backend` pointing at a backend that no longer exists.

### Crawl4AI

Crawl4AI pulls about 35 packages, so it is not installed into Hermes's environment: `setup` creates a separate one with `hermes pm` (`HERMES_HOME/environments/grounded-web-crawl4ai`).

grounded-web downloads no browser. Crawl4AI drives the Chromium that Hermes's own browser tool uses, found the way Hermes finds it: `browser.executable_path` in `config.yaml`, then the Chromium installed by `hermes pm install chromium` (pinned and checked by Hermes), then `/etc/hermes/chromium-executable-path` (Docker image), then a `chromium` on PATH. If there is none, `setup` offers `hermes pm install chromium`. For each page, a fresh headless instance starts with a temporary profile and a DevTools port on 127.0.0.1, Crawl4AI connects to it, and it is stopped and its profile deleted when the page is read.

Without Crawl4AI, pages are read with trafilatura only, and lists and tables it takes for page furniture (the plan list above) stay out.

### Local OCR

Scanned PDFs hold page images, not text. With OCR installed, grounded-web renders the scanned pages (pypdfium2) and reads them with RapidOCR (PaddleOCR models in ONNX format, run by onnxruntime): no language model, no service, about 1 second per page, up to 30 pages per document. Like Crawl4AI, it lives in its own `hermes pm` environment (`HERMES_HOME/environments/grounded-web-ocr`, about 250 MB). On first use RapidOCR downloads its models (about 32 MB) from its official repository on modelscope.cn and checks each one against the SHA-256 it ships with.

Hermes's own `read_file` routes scanned pages to a vision model instead (`vision_analyze`); grounded-web keeps that for what OCR cannot read, such as figures and handwriting.

## Settings

Under Settings → Plugins in Hermes Desktop, or `plugins.entries.grounded-web.settings` in `config.yaml`:

| Key | Default | Meaning |
|---|---|---|
| `language` | `auto` | Footer language: `auto` (Hermes's `display.language`; English for languages other than en/fr), `answer` (the reply's language), `en` or `fr` |
| `show_sources` | `auto` | `auto`: list the opened pages, unless another plugin also rewrites replies (see below). `always`: list them anyway. `never`: no list |
| `remind` | `true` | Add one sentence to each user message (about 50 tokens): search snippets are not sources, open the pages |

Search and page reading are separate settings: grounded-web only reads pages. It works with any search backend.

## What it does, for review

- **Hooks:** `pre_llm_call` (starts a record for the turn and, unless `remind` is off, appends the one-sentence reminder to the user message), `post_tool_call` (keeps the text of `web_extract` results), `transform_llm_output` (appends the footer; the answer itself is not changed, so a streamed answer is not printed twice).
- **Web provider:** `grounded-web`, extract only.
- **CLI:** `hermes grounded-web status|setup|uninstall`.
- **Skill:** `grounded-web:web-research`, read-only, loaded only if you auto-load it or call it.
- **Network:** downloads the URLs the agent asks `web_extract` to read, directly from this machine with a desktop browser user agent. `setup` also checks the SearXNG URL you give it and reads two test pages on iana.org; with OCR chosen, RapidOCR downloads its models once from modelscope.cn (SHA-256 checked). Crawl4AI's browser loads the same URLs and their page assets.
- **Processes:** one Crawl4AI child process per page, at most three at once, each stopped after 60 seconds; it starts Hermes's Chromium headless (DevTools port on 127.0.0.1, temporary profile) and stops it before exiting; one child process per document (Hermes's own Python running `doc_reader.py` with anydoc), stopped after 60 seconds; for a scanned PDF with OCR installed, one more child process (`ocr_runner.py` in the OCR environment), stopped after 180 seconds.
- **Writes:** `web.search_backend`, `web.extract_backend`, `skills.auto_load` and, for SearXNG, `SEARXNG_URL` in `.env`, all through Hermes's own config functions and only during `setup` and `uninstall`; the values `setup` replaced, in `HERMES_HOME/plugin-data/grounded-web/previous.json`; the Chromium path, in `browser.json` next to it. Nothing else is stored: page text lives in memory only, for at most 30 pages per conversation and 20 conversations, and is gone when Hermes stops.
- **Reads:** the `plugin.yaml` of other installed plugins, to find reply rewriters; `hermes pm env chromium` and `browser.executable_path`, during `setup`, to find Hermes's Chromium.
- **No telemetry**, no credentials read, no self-update.

## Other plugins that rewrite replies

Hermes runs every plugin's `transform_llm_output` hook but keeps only the first rewrite of a reply, so two plugins that append a footer hide one another without warning. grounded-web looks for any other enabled plugin that declares that hook: it reads the `plugin.yaml` of the plugins installed in `HERMES_HOME/plugins` (the catalog requires declared hooks to match what a plugin registers) and asks Hermes whether each one is enabled (`ctx.has_plugin`). Plugins installed with pip have no manifest there and are not seen. With `show_sources: auto` it then adds nothing and leaves the reply to that plugin. `hermes grounded-web status` names the plugin. Set `show_sources: always` to show grounded-web's footer instead, or disable the other plugin. Page reading and the reminder keep working either way.

## Limits

- The footer says which pages the answer was built from. It does not check that each sentence of the answer matches them: that would take another model call per reply and still not be reliable.
- An earlier page is matched on values with a unit, a price or a version; an answer that reuses only its prose is not linked to it.
- Pages behind logins or strong bot protection cannot be read; they come back as errors.

## Dependencies

Declared in `pyproject.toml`, installed by Hermes inside its own constraints:

| Package | Range | Floor chosen because |
|---|---|---|
| trafilatura | `>=1.10,<3` | oldest release that accepts lxml 6, which Hermes pins (tested 1.10 to 2.3) |
| rapidocr, onnxruntime, pypdfium2 | `>=3.10,<4`, `>=1.20,<2`, `>=5,<6` | separate OCR environment, installed by `setup`; tested with RapidOCR 3.10, onnxruntime 1.31 and Python 3.14 |
| crawl4ai | `>=0.9.1,<0.10` | separate environment, installed by `setup`; 0.9.0 and older need lxml 5, which has no Python 3.14 wheels (tested 0.9.1 to 0.9.5) |

## Development

```
python tools/check.py
```

Runs everything locally, no cloud CI: for Python 3.11 and 3.14, `uv` builds a throwaway environment with the dependencies from `pyproject.toml` (only releases at least 3 days old, the release-age quarantine the Hermes plugin guide recommends) and runs the tests; then the Hermes on the machine runs `hermes plugins doctor . --ci` (loads the plugin the way Hermes does) and `hermes plugins validate . --install-deps` (the catalog CI check). `--python 3.12` tests other versions, `--skip-hermes` runs the tests only.

The tests use made-up pages and need no network; the document tests start a child Python. Documents are read with anydoc (`firecrawl-anydoc`), which Hermes provides, so it is not a plugin dependency; `tools/check.py` installs it in the test environment.

## License

MIT
