---
name: firecrawl
description: "Firecrawl: fetch, search, extract and crawl the web where stock WebFetch/WebSearch fail (403, empty SPA shell, anti-bot, JS rendering), when live facts and prices are needed from the vendor's own page, for structured extract over a list of URLs, or a site crawl/map. Triggers: scrape, pull a page, anti-bot, render JS, live vendor prices, site crawl, link map, parse a site."
---

Gain only in fetch/extract; `/search` uses the WebSearch index.

## When

- WebFetch gave 403 / empty shell; a fact or price from the vendor's own page; field X for N providers → `extract`; site map or crawl → `map` / `crawl`.
- Not for ordinary search or what code/spec/memory answers; read vendor facts from its page.

## MCP (where present)

The MCP is set up per project and may be absent here: then use curl. Tools (loaded via ToolSearch like any deferred ones) `mcp__firecrawl__firecrawl_` + `scrape` (page → markdown), `search`, `extract` (schema over URLs), `map`, `crawl` + `check_crawl_status` (async, costly). An MCP added mid-session appears only after restart/reconnect of Claude Code → curl.

## curl fallback

Key from its untracked file:

```bash
KEY=$(cat ~/.claude/firecrawl-api-key)
```

Header `Authorization: Bearer $KEY`; `-o` a scratchpad file, slice with python:

```bash
curl -sS -X POST https://api.firecrawl.dev/v2/scrape \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","formats":["markdown"]}' -o out.json
python3 -c "import json;print(json.load(open('out.json'))['data']['markdown'][:4000])"

# search
curl -sS -X POST https://api.firecrawl.dev/v2/search \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"query":"...","limit":5}' -o s.json

# extract by schema from several URLs
curl -sS -X POST https://api.firecrawl.dev/v2/extract \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"urls":["https://a.com","https://b.com"],"prompt":"...","schema":{...}}' -o e.json
```

## Rules

- Paid: no `crawl` without `limit`; one fact → `scrape`.
- Key only in `~/.claude/firecrawl-api-key` (untracked) and the local MCP config; not in code, repo or `.mcp.json`.
