# grounded-web

A Hermes Agent plugin for web answers you can check.

- **Reads pages and PDFs on your machine** for `web_extract`: no API key, no extraction service.
- **Lists the pages the answer really used**, under the answer, with clickable links. Pages are taken from the tool results, never from the model's text, so the list cannot name a page that was not read.
- **Checks the answer's values against those pages**: every number with a unit, price, version and large number in the answer must appear in an opened page, and disagreements between pages are found. The check is plain code: no tokens, no model call. Its result is shown only when you turn on `verify`.

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

With `verify: true`, the check is added below the sources. For that answer:

```
✓ All 8 numbers in this answer appear in the opened pages.
```

And when a model writes a value no opened page holds (Qwen3-8B, asked for the latest llama.cpp release, with the releases page open):

```
⚠ The number in this answer is not in the opened pages: v0.5.2
```

Links are written out in full rather than as Markdown links: the Hermes CLI prints replies as plain text, where a bare link stays clickable (Ctrl+click in Windows Terminal) and Desktop and chat apps link it too.

The footer is in English or French. By default it follows Hermes's `display.language`, like Hermes's own notices; set `language: answer` to follow the language of the reply instead.

## Why

A web answer can go wrong in three places, and the model cannot see any of them.

1. **The page reader drops the data.** Main-text extractors discard what looks like page furniture. On the Nous Portal home page, trafilatura keeps the text but drops the plan list with each plan's Cloud agent size ("up to 4 GB RAM and 25 GB disk", "up to 8 GB RAM and 100 GB disk"). Without it, the answer above could not be given from that page.
2. **A source drops the context.** Third-party pages copy a figure without its condition (which plan, which connector, which model size), or from a sibling product. A model that reads only that page repeats it faithfully.
3. **The model fills gaps from memory.** In tests, local models wrote version numbers, core counts and power figures that were on none of the pages they had opened, like the `v0.5.2` above.

grounded-web fixes the first and makes the other two visible.

## How a page is read

1. Download it. An HTTP error (404, 410, 5xx) is reported as an error, unless a browser can still open the page.
2. PDF: text with pypdf. HTML: main text with trafilatura.
3. With Crawl4AI installed, the same page is also opened in a headless browser. Lines of the browser view that hold values missing from the main text, such as spec table rows, are appended under "More values from this page". Pages that trafilatura cannot read, because scripts build them, use the browser view instead.
4. Bot walls ("Just a moment...", "Automated bot check") and short error pages that answer HTTP 200 are reported as errors, in Hermes's `HTTP <code> from origin: ...` form. Hermes then does not re-fetch them through its keyless rescue (an outside service that can return the same wall as content), and a wall that another backend returns is never listed as a source.

Each page is capped at 30,000 characters.

## How the check works

After each turn that used a web tool, the plugin compares the final answer with the text of every page `web_extract` returned in the conversation so far, so an answer may rely on a page opened a few turns earlier; such pages are listed as "opened earlier". With no page opened at all, it checks against the search snippets and says so.

- Spellings are matched: `1 344 Go/s` = `1,344 GB/sec`, `65,3 TFLOPS` = `65.3 TFLOPS¹`, `256‑bit` = `256-bit`, and a unit in a table header (`| AI TOPS | 2064 |`) counts.
- Small bare numbers (generations, counts), product codes (`GB203-400-A1`), links and any source list the model wrote itself are skipped.
- A conflict is two pages giving different values with the same unit after the same words.

It does not decide which source is right, and it does not check claims without numbers.

## Install

Requires Hermes Agent 0.22.6 or later.

```
hermes plugins install ElSerda/Grounded-Web
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

### Uninstall

```
hermes grounded-web uninstall
hermes plugins remove grounded-web
```

`uninstall` puts back the web backends `setup` replaced (it records them in `HERMES_HOME/plugin-data/grounded-web`), removes the skill from `skills.auto_load`, and deletes the Crawl4AI environment and its browser files. A browser folder is kept when another Playwright install on the machine declares the same version. `hermes plugins remove` alone would leave `web.extract_backend` pointing at a backend that no longer exists.

### Crawl4AI

Crawl4AI pulls about 35 packages and a browser, so it is not installed into Hermes's environment. `setup` creates a separate environment with `hermes pm` (`HERMES_HOME/environments/grounded-web-crawl4ai`). It then downloads Playwright's headless Chromium shell (about 280 MB) to Playwright's browser folder (`%LOCALAPPDATA%\ms-playwright` on Windows, `~/.cache/ms-playwright` on Linux, `~/Library/Caches/ms-playwright` on macOS). That folder is outside `HERMES_HOME`: uninstalling Hermes does not remove it.

Without Crawl4AI, pages are read with trafilatura only, and lists and tables it takes for page furniture (the plan list above) stay out.

## Settings

Under Settings → Plugins in Hermes Desktop, or `plugins.entries.grounded-web.settings` in `config.yaml`:

| Key | Default | Meaning |
|---|---|---|
| `language` | `auto` | Footer language: `auto` (Hermes's `display.language`; English for languages other than en/fr), `answer` (the reply's language), `en` or `fr` |
| `show_sources` | `auto` | `auto`: list the opened pages, unless another plugin also rewrites replies (see below). `always`: list them anyway. `never`: no list |
| `verify` | `false` | Show the value check under the sources |
| `remind` | `true` | Add one sentence to each user message (about 50 tokens): search snippets are not sources, open the pages |

Search and page reading are separate settings: grounded-web only reads pages. It works with any search backend.

## What it does, for review

- **Hooks:** `pre_llm_call` (starts a record for the turn and, unless `remind` is off, appends the one-sentence reminder to the user message), `post_tool_call` (keeps the text of `web_extract` results), `transform_llm_output` (appends the footer; the answer itself is not changed, so a streamed answer is not printed twice).
- **Web provider:** `grounded-web`, extract only.
- **CLI:** `hermes grounded-web status|setup|uninstall`.
- **Skill:** `grounded-web:web-research`, read-only, loaded only if you auto-load it or call it.
- **Network:** downloads the URLs the agent asks `web_extract` to read, directly from this machine with a desktop browser user agent. `setup` also checks the SearXNG URL you give it and reads two test pages on iana.org. Crawl4AI's browser loads the same URLs and their page assets.
- **Processes:** one Crawl4AI child process per page, at most three at once, each stopped after 60 seconds.
- **Writes:** `web.search_backend`, `web.extract_backend`, `skills.auto_load` and, for SearXNG, `SEARXNG_URL` in `.env`, all through Hermes's own config functions and only during `setup` and `uninstall`; the values `setup` replaced, in `HERMES_HOME/plugin-data/grounded-web/previous.json`. Nothing else is stored: page text lives in memory only, for at most 30 pages per conversation and 20 conversations, and is gone when Hermes stops.
- **Reads:** the `plugin.yaml` of other installed plugins, to find reply rewriters; Playwright's `.links` registrations and `browsers.json`, during `uninstall` only.
- **No telemetry**, no credentials read, no self-update.

## Other plugins that rewrite replies

Hermes runs every plugin's `transform_llm_output` hook but keeps only the first rewrite of a reply, so two plugins that append a footer hide one another without warning. grounded-web looks for any other enabled plugin that declares that hook: it reads the `plugin.yaml` of the plugins installed in `HERMES_HOME/plugins` (the catalog requires declared hooks to match what a plugin registers) and asks Hermes whether each one is enabled (`ctx.has_plugin`). Plugins installed with pip have no manifest there and are not seen. With `show_sources: auto` it then adds nothing and leaves the reply to that plugin. `hermes grounded-web status` names the plugin. Set `show_sources: always` to show grounded-web's footer instead, or disable the other plugin. Page reading and the reminder keep working either way.

## Limits

- The check confirms that a value appears in an opened page. It cannot tell whether that page is right, unless another opened page disagrees.
- A disagreement can be two correct values for different conditions (two plans, two connectors). It shows where to look, not which page is wrong.
- Values without a number and unit it knows (`3-slot`, `5th generation`, `Qwen3`) are not checked. Model sizes (`70B`) and context lengths (`128K`) are.
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
