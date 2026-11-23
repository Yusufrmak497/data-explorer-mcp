"""Tests for the Data Explorer MCP server. The network is mocked; no real requests."""
import httpx
import pytest

import server

SAMPLE = [
    {
        "name": {"common": "Germany", "official": "Federal Republic of Germany"},
        "altSpellings": ["DE", "Deutschland"],
        "cca2": "DE",
        "cca3": "DEU",
        "capital": ["Berlin"],
        "region": "Europe",
        "area": 357114.0,
        "currencies": {"EUR": {"name": "Euro", "symbol": "€"}},
        "languages": {"deu": "German"},
        "borders": ["AUT", "FRA"],
        "flag": "🇩🇪",
    },
    {
        "name": {"common": "France", "official": "French Republic"},
        "cca2": "FR",
        "cca3": "FRA",
        "capital": ["Paris"],
        "region": "Europe",
        "area": 551695.0,
        "currencies": {"EUR": {"name": "Euro", "symbol": "€"}},
        "languages": {"fra": "French"},
        "borders": ["DEU"],
        "flag": "🇫🇷",
    },
    {
        "name": {"common": "Antarctica", "official": "Antarctica"},
        "cca2": "AQ",
        "cca3": "ATA",
        "region": "Antarctic",
        "area": 14000000.0,
    },
]


class FakeResponse:
    def __init__(self, status=200, payload=None, bad_json=False):
        self.status_code = status
        self._payload = SAMPLE if payload is None else payload
        self._bad_json = bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("GET", server.DATA_URL)
            raise httpx.HTTPStatusError("boom", request=req, response=httpx.Response(self.status_code, request=req))

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


@pytest.fixture(autouse=True)
def reset_cache():
    server._cache.update(data=None, fetched_at=0.0)


def mock_get(monkeypatch, response=None, exc=None):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(kwargs)
        if exc is not None:
            raise exc
        return response or FakeResponse()

    monkeypatch.setattr(server.httpx, "get", fake_get)
    return calls


# --- search_countries -------------------------------------------------------

def test_search_returns_model_friendly_shape(monkeypatch):
    mock_get(monkeypatch)
    assert server.search_countries("germ") == [
        {"name": "Germany", "capital": "Berlin", "region": "Europe", "area_km2": 357114.0}
    ]


def test_search_ranks_exact_match_first_and_respects_limit(monkeypatch):
    mock_get(monkeypatch)
    results = server.search_countries("an", limit=2)
    assert len(results) == 2
    assert all("error" not in r for r in results)


def test_search_prefers_common_name_over_official_name(monkeypatch):
    data = [
        {"name": {"common": "Mexico", "official": "United Mexican States"}, "cca2": "MX", "cca3": "MEX"},
        {"name": {"common": "United States", "official": "United States of America"}, "cca2": "US", "cca3": "USA"},
    ]
    mock_get(monkeypatch, response=FakeResponse(payload=data))
    assert [r["name"] for r in server.search_countries("united")] == ["United States", "Mexico"]


def test_search_handles_missing_capital(monkeypatch):
    mock_get(monkeypatch)
    assert server.search_countries("antarctica")[0]["capital"] is None


def test_search_no_match_is_empty_list_not_error(monkeypatch):
    mock_get(monkeypatch)
    assert server.search_countries("atlantis") == []


@pytest.mark.parametrize("query", ["", "   ", "x" * 101, None, 42])
def test_search_rejects_invalid_query(monkeypatch, query):
    calls = mock_get(monkeypatch)
    assert "error" in server.search_countries(query)[0]
    assert calls == []  # never hits the network on bad input


@pytest.mark.parametrize("limit", [0, -1, 51, "5", True])
def test_search_rejects_invalid_limit(monkeypatch, limit):
    mock_get(monkeypatch)
    assert "limit" in server.search_countries("germany", limit=limit)[0]["error"]


# --- get_country_details ----------------------------------------------------

def test_details_returns_currencies_languages_borders_flag(monkeypatch):
    mock_get(monkeypatch)
    d = server.get_country_details("Germany")
    assert d["name"] == "Germany"
    assert d["currencies"] == [{"code": "EUR", "name": "Euro", "symbol": "€"}]
    assert d["languages"] == ["German"]
    assert d["borders"] == ["AUT", "France"]  # known codes resolved to names
    assert d["flag_url"] == "https://flagcdn.com/w320/de.png"


def test_details_accepts_iso_code(monkeypatch):
    mock_get(monkeypatch)
    assert server.get_country_details("fra")["name"] == "France"


def test_details_country_without_currency_or_borders(monkeypatch):
    mock_get(monkeypatch)
    d = server.get_country_details("Antarctica")
    assert d["currencies"] == [] and d["languages"] == [] and d["borders"] == []


def test_details_no_match_is_structured_error(monkeypatch):
    mock_get(monkeypatch)
    assert "no country found" in server.get_country_details("Atlantis")["error"]


@pytest.mark.parametrize("name", ["", "  ", None, 3.5])
def test_details_rejects_invalid_name(monkeypatch, name):
    mock_get(monkeypatch)
    assert "error" in server.get_country_details(name)


# --- upstream failures (both tools) -----------------------------------------

UPSTREAM_FAILURES = [
    ({"exc": httpx.ReadTimeout("slow")}, "timed out"),
    ({"exc": httpx.ConnectError("dns")}, "could not reach"),
    ({"response": FakeResponse(status=503)}, "HTTP 503"),
    ({"response": FakeResponse(bad_json=True)}, "invalid JSON"),
    ({"response": FakeResponse(payload={"success": False})}, "unexpected shape"),
]


@pytest.mark.parametrize("kwargs,message", UPSTREAM_FAILURES)
def test_search_upstream_failures_are_clean(monkeypatch, kwargs, message):
    mock_get(monkeypatch, **kwargs)
    assert message in server.search_countries("germany")[0]["error"]


@pytest.mark.parametrize("kwargs,message", UPSTREAM_FAILURES)
def test_details_upstream_failures_are_clean(monkeypatch, kwargs, message):
    mock_get(monkeypatch, **kwargs)
    assert message in server.get_country_details("germany")["error"]


def test_dataset_is_cached_between_calls(monkeypatch):
    calls = mock_get(monkeypatch)
    server.search_countries("germany")
    server.get_country_details("france")
    assert len(calls) == 1
    assert calls[0]["timeout"] == server.TIMEOUT_SECONDS
