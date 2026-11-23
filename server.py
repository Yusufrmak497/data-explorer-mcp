"""Data Explorer — MCP server for Week 5.

Exposes country data to an agent as two MCP tools over STDIO:

- ``search_countries(query, limit)``  — find countries by name
- ``get_country_details(name)``       — currencies, languages, borders, flag URL

Data source
-----------
The starter wrapped the REST Countries ``/v3.1`` API. That version was shut down
(it now answers every request with ``"This API version has been deprecated"``) and the
replacement ``/v5`` API requires an account key. This server therefore reads the open
``mledoze/countries`` dataset — the dataset REST Countries is built from — over HTTPS
from GitHub, and does the name matching itself. Flag image URLs come from flagcdn.com.
The dataset has no population field, so ``search_countries`` returns ``area_km2``.

Every failure (bad input, HTTP error, timeout, malformed data, no match) is returned as
a structured ``{"error": ...}`` value. No exception ever escapes a tool, so the server
never crashes on bad input.

Setup:
    pip install -r requirements.txt
Run (STDIO):
    python server.py
"""
from __future__ import annotations

import time

import httpx
from mcp.server.fastmcp import FastMCP

DATA_URL = "https://raw.githubusercontent.com/mledoze/countries/master/countries.json"
FLAG_URL = "https://flagcdn.com/w320/{cca2}.png"
TIMEOUT_SECONDS = 10.0
CACHE_TTL_SECONDS = 3600
MAX_QUERY_LENGTH = 100
MAX_LIMIT = 50

mcp = FastMCP("data-explorer")

_cache: dict = {"data": None, "fetched_at": 0.0}


class UpstreamError(Exception):
    """The data source could not be reached or returned unusable data."""


def _load_countries() -> list[dict]:
    """Fetch the dataset once and keep it in memory for CACHE_TTL_SECONDS."""
    if _cache["data"] is not None and time.time() - _cache["fetched_at"] < CACHE_TTL_SECONDS:
        return _cache["data"]
    try:
        resp = httpx.get(DATA_URL, timeout=TIMEOUT_SECONDS, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except httpx.TimeoutException:
        raise UpstreamError(f"data source timed out after {TIMEOUT_SECONDS:.0f}s")
    except httpx.HTTPStatusError as exc:
        raise UpstreamError(f"data source returned HTTP {exc.response.status_code}")
    except httpx.HTTPError as exc:
        raise UpstreamError(f"could not reach data source: {type(exc).__name__}")
    except ValueError:
        raise UpstreamError("data source returned invalid JSON")
    if not isinstance(data, list) or not data:
        raise UpstreamError("data source returned an unexpected shape")
    _cache.update(data=data, fetched_at=time.time())
    return data


def _validate_name(value: object, field: str) -> str | dict:
    """Return the cleaned string, or an error dict."""
    if not isinstance(value, str):
        return {"error": f"{field} must be a string"}
    cleaned = value.strip()
    if not cleaned:
        return {"error": f"{field} must not be empty"}
    if len(cleaned) > MAX_QUERY_LENGTH:
        return {"error": f"{field} must be at most {MAX_QUERY_LENGTH} characters"}
    return cleaned


def _names(country: dict) -> list[str]:
    name = country.get("name") or {}
    names = [name.get("common") or "", name.get("official") or ""]
    names += country.get("altSpellings") or []
    return [n.lower() for n in names if n]


def _find(countries: list[dict], query: str) -> list[dict]:
    """Rank matches: exact name/code, then common name starts with the query, then any
    other name (official, alternative spelling) starts with it, then contains it."""
    q = query.lower()
    buckets: list[list[dict]] = [[], [], [], []]
    for c in countries:
        names = _names(c)
        common = ((c.get("name") or {}).get("common") or "").lower()
        codes = {str(c.get(k, "")).lower() for k in ("cca2", "cca3")}
        if q in names or q in codes:
            buckets[0].append(c)
        elif common.startswith(q):
            buckets[1].append(c)
        elif any(n.startswith(q) for n in names):
            buckets[2].append(c)
        elif any(q in n for n in names):
            buckets[3].append(c)
    return [c for bucket in buckets for c in bucket]


@mcp.tool()
def search_countries(query: str, limit: int = 5) -> list[dict]:
    """Search countries by name (common, official or alternative spelling).

    Returns up to ``limit`` items of {name, capital, region, area_km2}, best match first.
    An empty list means no country matched. Errors come back as [{"error": ...}].
    """
    cleaned = _validate_name(query, "query")
    if isinstance(cleaned, dict):
        return [cleaned]
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        return [{"error": f"limit must be an integer between 1 and {MAX_LIMIT}"}]
    try:
        countries = _load_countries()
    except UpstreamError as exc:
        return [{"error": str(exc)}]

    return [
        {
            "name": (c.get("name") or {}).get("common"),
            "capital": (c.get("capital") or [None])[0],
            "region": c.get("region"),
            "area_km2": c.get("area"),
        }
        for c in _find(countries, cleaned)[:limit]
    ]


@mcp.tool()
def get_country_details(name: str) -> dict:
    """Get details for one country: currencies, languages, bordering countries, flag URL.

    ``name`` may be a common or official name, or an ISO code such as "DE" or "DEU".
    Returns {"error": ...} when the input is invalid, nothing matches, or the data
    source fails.
    """
    cleaned = _validate_name(name, "name")
    if isinstance(cleaned, dict):
        return cleaned
    try:
        countries = _load_countries()
    except UpstreamError as exc:
        return {"error": str(exc)}

    matches = _find(countries, cleaned)
    if not matches:
        return {"error": f"no country found matching '{cleaned}'"}
    c = matches[0]
    by_code = {x.get("cca3"): (x.get("name") or {}).get("common") for x in countries}
    cca2 = str(c.get("cca2") or "").lower()

    return {
        "name": (c.get("name") or {}).get("common"),
        "official_name": (c.get("name") or {}).get("official"),
        "currencies": [
            {"code": code, "name": info.get("name"), "symbol": info.get("symbol")}
            for code, info in (c.get("currencies") or {}).items()
        ],
        "languages": sorted((c.get("languages") or {}).values()),
        "borders": [by_code.get(code, code) for code in (c.get("borders") or [])],
        "flag_url": FLAG_URL.format(cca2=cca2) if cca2 else None,
        "flag_emoji": c.get("flag"),
        "other_matches": [(m.get("name") or {}).get("common") for m in matches[1:4]],
    }


if __name__ == "__main__":
    mcp.run()
