"""Offline tests for google_finance: every endpoint function runs against
its recorded rpc traffic (google_finance/fixtures/*.json.gz, captured
2026-09-26 with record_fixtures.py) and the shape / key facts of the
output are asserted; plus the pure helpers (symbol parsing, row parsers,
robustness on truncated payloads).

    cd scrapers && python -m pytest google_finance/test_parsers.py -q
"""
import gzip
import json
import os
import sys
from contextlib import contextmanager
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_finance import (charts, fetch, fundamentals, holdings, insights, markets, news, parsers,  # noqa: E402
                            peers, quotes, symbols)

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
S = symbols.parse_symbol


@contextmanager
def replay(name):
    """Serve fetch's batch replies from a recorded fixture."""
    with gzip.open(os.path.join(FX, f"{name}.json.gz"), "rt", encoding="utf-8") as f:
        log = json.load(f)
    table = {}
    for rpcid, args, language, country, data in log:
        table.setdefault((rpcid, json.dumps(args)), []).append(data)
    real = fetch._replies

    def fake(calls, language, country, label):
        out = {}
        for i, (rpcid, args) in enumerate(calls):
            hits = table.get((rpcid, json.dumps(args)))
            assert hits, f"no recorded reply for {rpcid} {args}"
            data = hits[0]
            out[str(i + 1)] = (rpcid, None, data["error"]) if isinstance(data, dict) and "error" in data \
                else (rpcid, data, None)
        return out

    fetch._replies = fake
    symbols._cache.clear()
    try:
        yield
    finally:
        fetch._replies = real


# ---- symbols -------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("AAPL:NASDAQ", "AAPL:NASDAQ"),
    ("aapl:nasdaq", "AAPL:NASDAQ"),
    ("https://www.google.com/finance/quote/AAPL:NASDAQ?window=1M", "AAPL:NASDAQ"),
    ("https://www.google.com/finance/beta/quote/.INX:INDEXSP", ".INX:INDEXSP"),
    ("google.com/finance/quote/USD-INR", "USD-INR"),
    ("usd/inr", "USD-INR"),
    ("BTC-USD", "BTC-USD"),
    ("/m/07zmbvf", "/m/07zmbvf"),
    ("AAPL", "?AAPL"),
    ("BRK.B", "?BRK.B"),
    ("will-apple-release-iphone-18-in-2026:polymarket", "will-apple-release-iphone-18-in-2026:POLYMARKET"),
    ("cf2c678c-b81a-80c3-10d1-9c5e76448e51:crunchbase", "cf2c678c-b81a-80c3-10d1-9c5e76448e51:CRUNCHBASE"),
])
def test_parse_symbol(raw, expected):
    assert S(raw) == expected


@pytest.mark.parametrize("raw", ["", "not a symbol!", "https://example.com/finance/quote/AAPL:NASDAQ",
                                 "https://www.google.com/search?q=aapl"])
def test_parse_symbol_rejects(raw):
    with pytest.raises(ValueError):
        S(raw)


def test_descriptor():
    assert symbols.descriptor("AAPL:NASDAQ") == [None, ["AAPL", "NASDAQ"]]
    assert symbols.descriptor("USD-INR") == [None, None, ["USD", "INR"]]
    assert symbols.descriptor("/m/07zmbvf") == ["/m/07zmbvf"]


# ---- robustness ------------------------------------------------------------------------------

@pytest.mark.parametrize("fn", [parsers.ticker_row, parsers.earnings_row, parsers.analyst_rating,
                                parsers.insider_transaction, parsers.politician_trade, parsers.politician_holding,
                                parsers.news_item, parsers.chart_series, parsers.cited_point])
@pytest.mark.parametrize("junk", [None, [], [None], ["x"], [1, 2, 3], {"a": 1}, "text"])
def test_row_parsers_never_crash(fn, junk):
    fn(junk)


def test_block_parsers_tolerate_truncation():
    assert parsers.financials(None) == ([], [])
    assert parsers.financials([[[None, None, None, None, None, "/m/x", "GE", ["GE", "NYSE"]]]]) == ([], [])
    assert parsers.chart([]) == []
    assert parsers.news_sentiment([None, None, [["SPY", "NYSEARCA"], 0, 0, 0, 0]]) is None
    assert parsers.key_stats(None, None, None)["open"] is None
    assert parsers.not_found([[[None, [5]]]])


# ---- quotes ----------------------------------------------------------------------------------

def test_quote():
    with replay("quote_aapl"):
        q = quotes.quote(S("AAPL"))
    assert q["symbol"] == "AAPL:NASDAQ" and q["type"] == "stock" and q["currency"] == "USD"
    assert q["price"] > 0 and q["previous_close"] > 0 and q["market_cap"] > 10 ** 12
    assert q["day_low"] <= q["day_high"] and q["year_low"] <= q["year_high"]
    assert q["market_hours"]["opens_at"].endswith("-04:00")
    assert q["extended_hours"]["session"] in ("pre_market", "after_hours")
    assert q["link"] == "https://www.google.com/finance/quote/AAPL:NASDAQ"


def test_quotes_batch():
    with replay("quotes_mixed"):
        out = quotes.quotes([S(x) for x in ("AAPL:NASDAQ", "BTC-USD", ".INX:INDEXSP", "USD-INR", "FOOBARBAZ:NASDAQ")])
    assert [q["symbol"] for q in out["quotes"]] == ["AAPL:NASDAQ", "BTC-USD", ".INX:INDEXSP", "USD-INR"]
    assert out["not_found"] == ["FOOBARBAZ:NASDAQ"]
    types = {q["symbol"]: q["type"] for q in out["quotes"]}
    assert types == {"AAPL:NASDAQ": "stock", "BTC-USD": "cryptocurrency", ".INX:INDEXSP": "index", "USD-INR": "currency"}
    assert out["quotes"][3]["pair"]["quote_currency_name"] == "Indian Rupee"


def test_details_stock():
    with replay("details_aapl"):
        d = quotes.details(S("AAPL:NASDAQ"))
    assert d["profile"]["headquarters"]["city"] == "Cupertino" and d["profile"]["founded_date"] == "1976-04-01"
    assert d["profile"]["employees"] > 100000 and d["profile"]["wikipedia_link"].startswith("https://en.wikipedia")
    ks = d["key_stats"]
    assert ks["pe_ratio"] > 0 and ks["eps"] > 0 and ks["shares_outstanding"] > 10 ** 9
    assert ks["ex_dividend_date"] and ks["primary_exchange"] == "NASDAQ"
    assert d["logo"].startswith("data:image/svg+xml")
    ns = d["news_sentiment"]
    assert abs(ns["bullish_percent"] + ns["neutral_percent"] + ns["bearish_percent"] - 100) < 0.5
    assert d["fund"] is None and d["futures"] is None and d["currencies"] is None


def test_details_fund_futures_crypto_private():
    with replay("details_vfiax"):
        f = quotes.details(S("VFIAX:MUTF"))["fund"]
    assert f["category"] and f["expense_ratio_percent"] == 0.04 and f["morningstar_rating"] in range(1, 6)
    with replay("details_esw00"):
        d = quotes.details(S("ESW00:CME_EMINIS"))
    assert d["type"] == "futures" and d["futures"]["open_interest"] > 0 and d["futures"]["market_segment"] == "INDX"
    assert d["key_stats"]["year_high"] is None          # futures repeat the day range there
    with replay("details_btc"):
        d = quotes.details(S("BTC-USD"))
    assert d["type"] == "cryptocurrency" and [c["code"] for c in d["currencies"]] == ["BTC", "USD"]
    with replay("details_openai"):
        d = quotes.details(S("cf2c678c-b81a-80c3-10d1-9c5e76448e51:CRUNCHBASE"))
    pc = d["private_company"]
    assert d["type"] == "private_company" and pc["legal_name"] == "OpenAI OpCo, LLC" and pc["total_funding"] > 10 ** 11
    assert pc["employees_min"] == 1001 and pc["employees_max"] == 5000 and pc["description"]


def test_convert():
    with replay("convert_usd_eur"):
        c = quotes.convert("USD", "EUR", 250)
    assert c["to_currency_name"] == "Euro" and c["converted_amount"] == pytest.approx(c["exchange_rate"] * 250)


# ---- charts ----------------------------------------------------------------------------------

def test_chart_window_line():
    with replay("chart_1d"):
        c = charts.chart(S("AAPL:NASDAQ"), window="1D")
    assert c["format"] == "line" and c["interval"] == "1min" and c["count"] == len(c["prices"]) > 300
    sessions = {p["session"] for p in c["prices"]}
    assert "regular" in sessions
    assert c["prices"][0]["time"].startswith(("2026-", "2027-")) and c["prices"][0]["price"] > 0


def test_chart_range_candles():
    with replay("chart_range"):
        c = charts.chart(S("AAPL:NASDAQ"), start_date=date(2026, 1, 1), end_date=date(2026, 3, 31), interval="1day")
    assert c["format"] == "candles" and c["interval"] == "1day" and 55 <= c["count"] <= 65
    k = c["prices"][10]
    assert k["low"] <= min(k["open"], k["close"]) <= max(k["open"], k["close"]) <= k["high"]


def test_chart_compare_matches_series_by_symbol():
    with replay("chart_compare"):
        c = charts.chart(S("AAPL:NASDAQ"), window="1Y", compare=[S("MSFT:NASDAQ"), S("BTC-USD")])
    assert c["symbol"] == "AAPL:NASDAQ" and c["count"] > 200
    assert {x["symbol"] for x in c["comparisons"]} == {"MSFT:NASDAQ", "BTC-USD"}


def test_auto_interval():
    assert charts.auto_interval(date(2026, 1, 1), date(2026, 1, 5)) == "5min"
    assert charts.auto_interval(date(2026, 1, 1), date(2026, 1, 30)) == "30min"
    assert charts.auto_interval(date(2020, 1, 1), date(2026, 1, 1)) == "1week"


# ---- fundamentals ----------------------------------------------------------------------------

def test_financials():
    with replay("financials_aapl"):
        f = fundamentals.financials(S("AAPL:NASDAQ"), "annual", 3)
    assert f["count"] == 3 and f["total_periods"] > 20
    p = f["periods"][0]
    inc, bal, cf = p["income_statement"], p["balance_sheet"], p["cash_flow"]
    assert inc["revenue"] - inc["cost_of_revenue"] == inc["gross_profit"]
    assert inc["operating_expense"] == inc["research_and_development_expenses"] + inc["selling_general_and_admin_expenses"]
    assert bal["total_assets"] == bal["total_liabilities"] + bal["total_equity"]
    assert bal["cash_and_short_term_investments"] == bal["cash_and_equivalents"] + bal["short_term_investments"]
    assert cf["net_income"] == inc["net_income"] and cf["cash_from_operations"] > 0
    assert f["periods"][0]["period_end_date"] > f["periods"][1]["period_end_date"]


def test_earnings():
    with replay("earnings_aapl"):
        e = fundamentals.earnings(S("AAPL:NASDAQ"))
    r = e["reported"][0]
    assert r["is_reported"] and r["result"] in ("beat", "miss", "mixed") and r["eps"]["surprise_percent"] is not None
    assert e["next_report"] and not e["next_report"]["is_reported"] and e["next_report"]["eps"]["estimate"]
    assert all(x["period_end_date"] for x in e["reported"])


def test_earnings_call():
    with replay("earnings_call_aapl"):
        c = fundamentals.earnings_call(S("AAPL:NASDAQ"))
    assert c["has_transcript"] and c["segment_count"] == len(c["transcript"]) > 50
    seg = c["transcript"][0]
    assert seg["speaker"] and seg["text"] and seg["start_seconds"] < seg["end_seconds"]
    assert {d["type"] for d in c["documents"]} <= {"financial_report", "press_release", "document"}
    assert c["audio"]["mp3"].startswith("https://") and c["highlights"] and c["at_a_glance"][0]["sources"]


def test_analyst_ratings():
    with replay("analyst_ratings_aapl"):
        a = fundamentals.analyst_ratings(S("AAPL:NASDAQ"))
    assert a["buy_count"] + a["hold_count"] + a["sell_count"] == a["analyst_count"]
    pt = a["price_target"]
    assert pt["low"] <= pt["average"] <= pt["high"]
    r = a["ratings"][0]
    assert r["firm"] and r["date"] and r["analyst_stats"]["ranked_analysts"] > 1000


# ---- holdings --------------------------------------------------------------------------------

def test_holdings():
    with replay("insiders_aapl"):
        i = holdings.insider_transactions(S("AAPL:NASDAQ"))
    t = i["transactions"][0]
    assert t["transaction_type"] in ("buy", "sell") and t["shares"] > 0 and "sec.gov" in t["sec_filing_link"]
    assert i["has_more"] == bool(i["next_cursor"])
    with replay("politician_trades_aapl"):
        p = holdings.politician_trades(S("AAPL:NASDAQ"))
    tr = p["trades"][0]
    assert tr["transaction_type"] in ("buy", "sell") and tr["amount"]["min"] < tr["amount"]["max"]
    with replay("politician_holdings_aapl"):
        h = holdings.politician_holdings(S("AAPL:NASDAQ"))
    sh = h["holdings"][0]["shares"]
    assert sh["min"] <= sh["mid"] <= sh["max"]


def test_bad_cursor():
    with pytest.raises(ValueError):
        holdings.insider_transactions(S("AAPL:NASDAQ"), cursor="not base64 !!")


# ---- insights, news, peers -------------------------------------------------------------------

def test_insights():
    with replay("analysis_aapl"):
        a = insights.analysis(S("AAPL:NASDAQ"))
    assert a["summary"] and a["bullish_view"][0]["title"] and a["bearish_view"][0]["sources"][0]["link"]
    with replay("key_moments_aapl"):
        k = insights.key_moments(S("AAPL:NASDAQ"))
    m = k["moments"][0]
    assert m["date"] and m["direction"] in ("up", "down") and m["explanation"] and m["tags"]
    assert (m["change_percent"] > 0) == (m["direction"] == "up")
    with replay("prediction_markets_aapl"):
        p = insights.prediction_markets(S("AAPL:NASDAQ"))
    pm = p["markets"][0]
    assert pm["platform"] in ("Kalshi", "Polymarket") and 0 <= pm["probability_percent"] <= 100


def test_news_and_peers():
    with replay("news_aapl"):
        n = news.news(S("AAPL:NASDAQ"), 10)
    assert n["count"] == 10 and len({x["link"] for x in n["news"]}) == 10
    assert n["news"][0]["published_at"] >= n["news"][-1]["published_at"]
    with replay("similar_aapl"):
        s = peers.similar(S("AAPL:NASDAQ"), 5)
    assert s["count"] == 5 and "AAPL:NASDAQ" not in {x["symbol"] for x in s["similar"]}
    with replay("related_aapl"):
        r = peers.related(S("AAPL:NASDAQ"))
    assert r["related"][0]["latest_earnings"]["fiscal_year"]


# ---- markets ---------------------------------------------------------------------------------

def test_markets():
    with replay("search_apple"):
        s = markets.search("apple")
    assert s["results"][0]["symbol"] == "AAPL:NASDAQ"
    assert {"stock", "prediction_event"} <= {r["type"] for r in s["results"]}
    with replay("trending_us"):
        t = markets.trending()
    assert t["count"] and t["results"][0]["symbol"]
    with replay("market_summary_us"):
        m = markets.market_summary()
    assert {"us", "europe", "asia", "crypto", "futures", "currencies"} <= {r["region"] for r in m["regions"]}
    with replay("market_movers_in"):
        mv = markets.market_movers("all", "IN", limit=10)
    if mv["gainers"]:
        assert mv["gainers"][0]["change_percent"] >= mv["gainers"][-1]["change_percent"] > 0
    if mv["losers"]:
        assert mv["losers"][0]["change_percent"] < 0
    assert mv["most_active"][0]["rank"] == 1
    with replay("sectors_us"):
        sc = markets.sectors()
    assert sc["count"] == 11 and all(x["sector"] for x in sc["sectors"])
    with replay("earnings_calendar_us"):
        ec = markets.earnings_calendar()
    assert ec["earnings"] and ec["earnings"][0]["event"].endswith("Earnings Announcement")
    with replay("market_news_us"):
        mn = news.market_news(limit=5)
    assert mn["market_summary"][0]["sources"] and mn["latest_news"] and mn["top_stories"][0]["link"]
