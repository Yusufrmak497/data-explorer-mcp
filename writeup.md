# Week 4 — Data Explorer MCP Server

**Student:** Yusuf Irmak
**Tools used:** Claude Code (implementation, and as the MCP client), Python 3.12, `mcp` 1.30 (`FastMCP`), `httpx`

## 1. What was built
- **`search_countries(query, limit)`**: the worked example, hardened (see §3).
- **`get_country_details(name)`**: the new tool. It returns currencies (code, name, symbol),
  languages, borders resolved from ISO codes to country names, a flag image URL, and the
  flag emoji. It also returns `other_matches`, so the agent can tell when a name was ambiguous.
- **34 pytest tests** with the network mocked. They cover the return shapes, ranking, invalid input,
  timeouts, connection errors, HTTP 5xx, bad JSON, unexpected payloads, and caching.

### Two things in the starter were broken
1. **REST Countries v3.1 is gone.** `GET https://restcountries.com/v3.1/name/germany` now returns
   HTTP 200 with `{"success": false, "errors": [{"message": "This API version has been deprecated..."}]}`.
   The starter didn't treat that as an error, so it would crash on `c.get(...)`, because the body is a dict
   and not a list. The replacement `/v5` API answers `"Authorization key required."`. I switched to the open
   `mledoze/countries` dataset that REST Countries is built from. It is fetched over HTTPS and
   cached for one hour. Flag URLs come from `flagcdn.com`. That dataset has no population, so
   `search_countries` returns `area_km2` instead.
2. **`pip install mcp` now installs 2.x**, which removed `mcp.server.fastmcp`. Importing the
   starter failed with `ModuleNotFoundError ... FastMCP was renamed to MCPServer`. I pinned the requirement to `mcp>=1.2,<2`.

## 2. Transcript: an agent calling both tools
**Client:** Claude Code CLI (`claude -p`, model `claude-opus-5-5`). The server was registered through
the project's `.mcp.json`, and the agent was restricted to the two `data-explorer` tools. The full transcript is in
[`transcript.md`](transcript.md). The calls the agent made:

| # | Tool call | Result |
|---|---|---|
| 1 | `search_countries({"query": "united", "limit": 3})` | UAE, United Kingdom, United States Minor Outlying Islands |
| 2 | `get_country_details({"name": "Japan"})` | JPY ¥, Japanese, `borders: []`, `flag_url: https://flagcdn.com/w320/jp.png` |
| 3 | `get_country_details({"name": ""})` | `{"error": "name must not be empty"}` |
| 4 | `search_countries({"query": "united", "limit": 0})` | `[{"error": "limit must be an integer between 1 and 50"}]` |
| 5 | `get_country_details({"name": "Atlantis"})` | `{"error": "no country found matching 'Atlantis'"}` |

**The first agent run found a bug.** In that run, `search_countries("united", 3)` returned
*Mexico* as the third result. Mexico's **official** name, "United Mexican States", starts with
"united", and the ranking put every prefix match in the same bucket in dataset order. I split the ranking so that
common-name prefix matches come before official-name and alternative-spelling matches, and added a regression
test (`test_search_prefers_common_name_over_official_name`). The second run, shown above, is
correct.

The agent also pointed out that `search_countries` reports errors *inside the list*
(`[{"error": ...}]`), while `get_country_details` returns a top-level `{"error": ...}`. I kept
this on purpose. The list shape comes from the starter's contract, and each tool's docstring states its
error shape, so the model is told how errors look.

## 3. How errors are handled
- **Validate before any network call.** Inputs must be non-empty strings of at most 100 characters,
  and `limit` must be an int from 1 to 50 (`True` is rejected even though `bool` is a subclass of `int`). The tests
  check that invalid input never reaches `httpx.get`.
- **One place handles upstream failures.** `_load_countries()` turns every failure into an
  `UpstreamError` with a short, model-readable message: timeout (10 s), HTTP status error,
  connection error, invalid JSON, or a payload that isn't a non-empty list. The last check is
  exactly what catches the "deprecated API" body that broke the starter.
- **No match** returns `[]` for search (not an error) and a clear `no country found matching '…'` for
  details. A missing capital, currency, or border list becomes `null` or `[]` instead of a `KeyError`.
- **No exception escapes a tool**, so a bad call never kills the STDIO server and takes the client
  session down with it.
- Error messages say *what* failed without dumping stack traces or the full upstream response
  into the agent's context.

## 4. What I learned
On its own, an agent can only talk from what it already knows; the MCP server gives it two tools to query country data, and it can't touch anything beyond them, so I decide where the boundary is. The most surprising part was that all 34 tests passed, yet the first real agent run returned Mexico for "united": my tests only covered the cases I had thought of, while the agent used the tool in a way I hadn't. The broken starter taught the same lesson, because external APIs can change without warning. Error handling matters for the same reason: a crash would have killed the agent's session and a long stack trace would have filled its context with noise, but a short message like "no country found" lets it understand the problem and answer the user properly.
