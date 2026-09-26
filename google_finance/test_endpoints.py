"""Live endpoint smoke tests: one call per /google-finance/* route against
a running service, with example values proven to return data (2026-09-26).
The listing tooling reads each route's FIRST call from this file's AST as
its working example, so the values stay literals.

Skipped unless GOOGLE_FINANCE_BASE points at a running service:

    ONLY_SCRAPER=google-finance SCRAPERS_PORT=7431 python run.py
    GOOGLE_FINANCE_BASE=http://127.0.0.1:7431 python -m pytest google_finance/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("GOOGLE_FINANCE_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set GOOGLE_FINANCE_BASE to run live endpoint tests")


def call(path, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=120)
    assert resp.status_code == 200, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def status(path, **params):
    from curl_cffi import requests
    return requests.get(BASE + path, params=params, timeout=120).status_code


# ---- search & discovery ----------------------------------------------------------------------

def test_search():
    body = call("/google-finance/search", query="apple")
    assert body["results"][0]["symbol"] == "AAPL:NASDAQ" and body["results"][0]["price"]
    body = call("/google-finance/search", query="reliance", country="IN")
    assert body["results"][0]["symbol"] == "RELIANCE:NSE"
    body = call("/google-finance/search", query="openai")
    assert any(r["type"] == "private_company" and r["private_company"]["total_funding"] for r in body["results"])


def test_trending():
    body = call("/google-finance/trending", country="US")
    assert body["count"] >= 3 and body["results"][0]["symbol"]


# ---- quotes ----------------------------------------------------------------------------------

def test_quote():
    body = call("/google-finance/quote", symbol="AAPL:NASDAQ")
    assert body["price"] and body["previous_close"] and body["market_cap"] and body["year_high"]
    assert call("/google-finance/quote", symbol="AAPL")["symbol"] == "AAPL:NASDAQ"
    assert call("/google-finance/quote", symbol="https://www.google.com/finance/quote/BTC-USD")["type"] == "cryptocurrency"
    assert status("/google-finance/quote", symbol="FOOBARBAZ:NASDAQ") == 404
    assert status("/google-finance/quote", symbol="not a symbol!") == 400


def test_quotes():
    body = call("/google-finance/quotes", symbols="AAPL:NASDAQ,MSFT:NASDAQ,BTC-USD,.INX:INDEXSP,USD-INR")
    assert body["count"] == 5 and not body["not_found"]
    assert {q["type"] for q in body["quotes"]} == {"stock", "cryptocurrency", "index", "currency"}


def test_details():
    body = call("/google-finance/details", symbol="AAPL:NASDAQ")
    assert body["profile"]["ceo"] and body["profile"]["headquarters"]["city"] == "Cupertino"
    assert body["key_stats"]["pe_ratio"] and body["logo"].startswith("data:image") and body["news_sentiment"]
    assert call("/google-finance/details", symbol="VFIAX:MUTF")["fund"]["expense_ratio_percent"] is not None
    assert call("/google-finance/details", symbol="ESW00:CME_EMINIS")["futures"]["open_interest"]


def test_chart():
    body = call("/google-finance/chart", symbol="AAPL:NASDAQ", window="1D")
    assert body["format"] == "line" and body["count"] > 300 and body["prices"][0]["price"]
    body = call("/google-finance/chart", symbol="AAPL:NASDAQ", start_date="2026-01-01", end_date="2026-03-31",
                interval="1day")
    assert body["format"] == "candles" and 55 <= body["count"] <= 65 and body["prices"][0]["open"]
    body = call("/google-finance/chart", symbol="AAPL:NASDAQ", window="1Y", compare="MSFT:NASDAQ,BTC-USD")
    assert {c["symbol"] for c in body["comparisons"]} == {"MSFT:NASDAQ", "BTC-USD"}


def test_currency_convert():
    body = call("/google-finance/currency-convert", from_currency="USD", to_currency="EUR", amount="250")
    assert body["exchange_rate"] and body["converted_amount"] == pytest.approx(body["exchange_rate"] * 250, rel=1e-6)


# ---- fundamentals -----------------------------------------------------------------------------

def test_financials():
    body = call("/google-finance/financials", symbol="AAPL:NASDAQ", period="annual", limit="3")
    p = body["periods"][0]
    assert body["count"] == 3 and p["income_statement"]["revenue"] and p["balance_sheet"]["total_assets"]
    assert p["cash_flow"]["free_cash_flow"]


def test_earnings():
    body = call("/google-finance/earnings", symbol="AAPL:NASDAQ")
    assert body["reported"][0]["eps"]["actual"] is not None and body["reported"][0]["result"] in ("beat", "miss", "mixed")
    assert body["next_report"]["revenue"]["estimate"]


def test_earnings_call():
    body = call("/google-finance/earnings-call", symbol="AAPL:NASDAQ")
    assert body["has_transcript"] and body["transcript"][0]["speaker"] and body["highlights"]
    body = call("/google-finance/earnings-call", symbol="AAPL:NASDAQ", fiscal_year="2024", fiscal_quarter="1")
    assert body["fiscal_year"] == 2024 and body["segment_count"] > 20


def test_analyst_ratings():
    body = call("/google-finance/analyst-ratings", symbol="AAPL:NASDAQ")
    assert body["consensus"] and body["price_target"]["average"] and body["ratings"][0]["firm"]


# ---- holdings ---------------------------------------------------------------------------------

def test_insider_transactions():
    body = call("/google-finance/insider-transactions", symbol="AAPL:NASDAQ")
    assert body["transactions"][0]["insider"] and body["transactions"][0]["sec_filing_link"]
    if body["next_cursor"]:
        assert call("/google-finance/insider-transactions", symbol="AAPL:NASDAQ", cursor=body["next_cursor"])["count"]


def test_politician_trades():
    body = call("/google-finance/politician-trades", symbol="AAPL:NASDAQ")
    assert body["trades"][0]["politician"]["name"] and body["trades"][0]["amount"]["range"]


def test_politician_holdings():
    body = call("/google-finance/politician-holdings", symbol="AAPL:NASDAQ")
    assert body["holdings"][0]["shares"]["mid"] is not None


# ---- insights, news, peers ------------------------------------------------------------------

def test_analysis():
    body = call("/google-finance/analysis", symbol="AAPL:NASDAQ")
    assert body["summary"] and body["bullish_view"] and body["bearish_view"][0]["sources"]


def test_key_moments():
    body = call("/google-finance/key-moments", symbol="AAPL:NASDAQ")
    assert body["count"] and body["moments"][0]["explanation"] and body["moments"][0]["date"]


def test_prediction_markets():
    body = call("/google-finance/prediction-markets", symbol="AAPL:NASDAQ")
    assert body["markets"][0]["question"] and body["markets"][0]["probability_percent"] is not None


def test_news():
    body = call("/google-finance/news", symbol="AAPL:NASDAQ", limit="10")
    assert body["count"] == 10 and body["news"][0]["link"].startswith("http")


def test_similar():
    body = call("/google-finance/similar", symbol="AAPL:NASDAQ", limit="5")
    assert body["count"] == 5 and body["similar"][0]["price"]


def test_related():
    body = call("/google-finance/related", symbol="AAPL:NASDAQ")
    assert body["related"][0]["latest_earnings"]["revenue"]["actual"]


# ---- markets ----------------------------------------------------------------------------------

def test_market_summary():
    body = call("/google-finance/market-summary", country="US")
    assert {"us", "europe", "crypto", "futures"} <= {r["region"] for r in body["regions"]}


def test_market_movers():
    body = call("/google-finance/market-movers", country="IN", type="all", limit="10")
    assert len(body["most_active"]) == 10


def test_sectors():
    body = call("/google-finance/sectors", country="US")
    assert body["count"] >= 10 and body["sectors"][0]["sector"]


def test_earnings_calendar():
    body = call("/google-finance/earnings-calendar", period="upcoming", country="US")
    assert body["earnings"][0]["symbol"] and body["earnings"][0]["report_at"]


def test_market_news():
    body = call("/google-finance/market-news", country="US", limit="5")
    assert body["market_summary"] and body["latest_news"]
