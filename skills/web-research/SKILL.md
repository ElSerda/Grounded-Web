---
name: web-research
description: "Use for ANY web lookup: specs, news, prices, versions, facts, or 'find/search X'. Search, open the pages, answer from what they say."
version: 1.0.0
author: ElSerda
license: MIT
metadata:
  hermes:
    tags: [Research, Web, Search, Citations, Sources]
    category: research
    requires_tools: [web_search, web_extract]
---

# Web Research

Answer from pages you actually read. Search snippets only tell you which pages to open.

grounded-web adds the list of opened pages to your answer, then checks your values against them. Do not write a sources list.

## When to Use
- The user asks to search, find, check or compare something.
- The answer depends on facts that change or that you cannot be sure of: specs, prices, versions, news, dates.

## Procedure
1. Call `web_search` with a precise query. Keep product names and model numbers exact. Use English for technical topics.
2. Pick the 2 or 3 most relevant results. Prefer official sources: maker pages, datasheets, documentation.
3. Call `web_extract` with one URL per call, never several URLs together. It reads PDFs too, so open datasheets directly.
4. If a result returns `error`, open the next result. One failure never ends the research.
5. If the pages do not answer the question, search again with different words, up to 3 searches.
6. Answer using only facts found in the pages you opened.

## Rules
- Never answer from snippets alone when a page can be opened.
- Never say a tool cannot reach the information before trying it.
- If a fact was not found, say so plainly. Do not fill the gap from memory.
- If a fact comes from memory, mark it `(from memory, not verified)`.
- Keep numbers and units exactly as written in the source.
- If two sources disagree, give both values with their sources. Prefer the maker's page.
- If `web_search` itself fails, say so and retry once before giving up.

## Pitfalls
- Marketing pages often omit specs. Look for the datasheet or a detailed review.
- Reseller and review pages can copy the wrong values. Prefer the maker when values differ.
- A `<persisted-output>` result is only a preview. Read the saved file with `read_file` before using it.

## Verification
Before answering, check that you called `web_extract` and that the facts you give appear in those pages.
