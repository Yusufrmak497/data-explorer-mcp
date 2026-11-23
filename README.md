# Data Explorer — MCP Server (Week 5)

A `FastMCP` server, run over **STDIO**, that gives an agent two tools for looking up country data.

## Why the data source changed
The starter wrapped the REST Countries **`/v3.1`** API. That API has been **shut down**:
every `/v1`–`/v4` request now returns
`{"success": false, "errors": [{"message": "This API version has been deprecated..."}]}`,
and the new `/v5` API requires an account key (`"Authorization key required."`).

This server reads the open **[`mledoze/countries`](https://github.com/mledoze/countries)** dataset instead.
REST Countries is built from this dataset. It is fetched over HTTPS once and cached in memory for one hour.
Flag images come from **flagcdn.com**. The dataset has no population field, so
`search_countries` returns `area_km2` instead.

The starter's `requirements.txt` also installed **mcp 2.x**, which removed
`mcp.server.fastmcp` (it was renamed to `MCPServer`). The requirement is pinned to `mcp>=1.2,<2`
so the starter's `FastMCP` API still works.

## Install
```bash
python3 -m venv .venv            # Python 3.10+ (tested on 3.12)
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

## Run
```bash
.venv/bin/python server.py       # speaks MCP over STDIO; normally started by the client
.venv/bin/pytest -q              # 34 tests, network fully mocked
```

## Register in an MCP client
**Claude Code.** This repo ships a project-scoped [`.mcp.json`](.mcp.json). Run `claude` in this
folder and approve the `data-explorer` server. To register it manually:
```bash
claude mcp add data-explorer -- /absolute/path/.venv/bin/python /absolute/path/server.py
```
**Claude Desktop.** Add the following to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "data-explorer": {
      "command": "/absolute/path/.venv/bin/python",
      "args": ["/absolute/path/server.py"]
    }
  }
}
```

## Tool reference

### `search_countries(query: str, limit: int = 5) -> list[dict]`
This tool finds countries by common name, official name, alternative spelling, or ISO code.
Results are ranked in this order:
1. exact matches
2. the common name starts with the query
3. another name starts with the query
4. a name contains the query

| Param | Type | Rules |
|---|---|---|
| `query` | string | required, 1–100 characters after trimming |
| `limit` | int | 1–50, default 5 |

Example: `search_countries("united", 3)` returns
```json
[{"name": "United Arab Emirates", "capital": "Abu Dhabi", "region": "Asia", "area_km2": 83600},
 {"name": "United Kingdom", "capital": "London", "region": "Europe", "area_km2": 242900},
 {"name": "United States Minor Outlying Islands", "capital": null, "region": "Americas", "area_km2": 34.2}]
```
When nothing matches, the tool returns `[]`. That is not an error. Errors come back as `[{"error": "..."}]`.

### `get_country_details(name: str) -> dict`
This tool returns currencies, languages, bordering countries (as names), and a flag URL for the best match.

| Param | Type | Rules |
|---|---|---|
| `name` | string | required, 1–100 characters; accepts common or official names and ISO codes (`DE`, `DEU`) |

Example: `get_country_details("Turkey")` returns
```json
{"name": "Türkiye", "official_name": "Republic of Türkiye",
 "currencies": [{"code": "TRY", "name": "Turkish lira", "symbol": "₺"}],
 "languages": ["Turkish"],
 "borders": ["Armenia", "Azerbaijan", "Bulgaria", "Georgia", "Greece", "Iran", "Iraq", "Syria"],
 "flag_url": "https://flagcdn.com/w320/tr.png", "flag_emoji": "🇹🇷", "other_matches": []}
```
`other_matches` lists up to three more candidates, so the agent can notice when a name was ambiguous.

### Errors (both tools)
| Situation | Returned message |
|---|---|
| empty, whitespace-only, non-string or too-long input | `query must not be empty`, `name must be a string`, … |
| bad `limit` | `limit must be an integer between 1 and 50` |
| no country found (details) | `no country found matching 'Atlantis'` |
| timeout (10 s) | `data source timed out after 10s` |
| HTTP 4xx/5xx | `data source returned HTTP 503` |
| network failure | `could not reach data source: ConnectError` |
| invalid JSON or unexpected shape | `data source returned invalid JSON` / `... unexpected shape` |

The server is never crashed by any of these. Invalid input is rejected before any network call is made.
