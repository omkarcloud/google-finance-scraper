"""Record the raw rpc traffic of every endpoint scenario into
google_finance/fixtures/<scenario>.json.gz, so test_parsers.py can replay
whole endpoints offline:

    cd scrapers && python -m google_finance.record_fixtures            # all
    cd scrapers && python -m google_finance.record_fixtures quote_aapl # one

A fixture is a list of [rpcid, args, language, country, data | {"error": code}].
"""
import gzip
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_finance import (charts, fetch, fundamentals, holdings, insights, markets, news, peers,  # noqa: E402
                            quotes, symbols)

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
S = symbols.parse_symbol

SCENARIOS = {
    "quote_aapl": lambda: quotes.quote(S("AAPL")),
    "quotes_mixed": lambda: quotes.quotes([S(x) for x in ("AAPL:NASDAQ", "BTC-USD", ".INX:INDEXSP", "USD-INR",
                                                          "FOOBARBAZ:NASDAQ")]),
    "details_aapl": lambda: quotes.details(S("AAPL:NASDAQ")),
    "details_vfiax": lambda: quotes.details(S("VFIAX:MUTF")),
    "details_esw00": lambda: quotes.details(S("ESW00:CME_EMINIS")),
    "details_btc": lambda: quotes.details(S("BTC-USD")),
    "details_openai": lambda: quotes.details(S("cf2c678c-b81a-80c3-10d1-9c5e76448e51:CRUNCHBASE")),
    "convert_usd_eur": lambda: quotes.convert("USD", "EUR", 250),
    "chart_1d": lambda: charts.chart(S("AAPL:NASDAQ"), window="1D"),
    "chart_range": lambda: charts.chart(S("AAPL:NASDAQ"), start_date=date(2026, 1, 1), end_date=date(2026, 3, 31),
                                        interval="1day"),
    "chart_compare": lambda: charts.chart(S("AAPL:NASDAQ"), window="1Y", compare=[S("MSFT:NASDAQ"), S("BTC-USD")]),
    "financials_aapl": lambda: fundamentals.financials(S("AAPL:NASDAQ"), "annual", 3),
    "earnings_aapl": lambda: fundamentals.earnings(S("AAPL:NASDAQ")),
    "earnings_call_aapl": lambda: fundamentals.earnings_call(S("AAPL:NASDAQ")),
    "analyst_ratings_aapl": lambda: fundamentals.analyst_ratings(S("AAPL:NASDAQ")),
    "insiders_aapl": lambda: holdings.insider_transactions(S("AAPL:NASDAQ")),
    "politician_trades_aapl": lambda: holdings.politician_trades(S("AAPL:NASDAQ")),
    "politician_holdings_aapl": lambda: holdings.politician_holdings(S("AAPL:NASDAQ")),
    "analysis_aapl": lambda: insights.analysis(S("AAPL:NASDAQ")),
    "key_moments_aapl": lambda: insights.key_moments(S("AAPL:NASDAQ")),
    "prediction_markets_aapl": lambda: insights.prediction_markets(S("AAPL:NASDAQ")),
    "news_aapl": lambda: news.news(S("AAPL:NASDAQ"), 10),
    "similar_aapl": lambda: peers.similar(S("AAPL:NASDAQ"), 5),
    "related_aapl": lambda: peers.related(S("AAPL:NASDAQ")),
    "search_apple": lambda: markets.search("apple"),
    "trending_us": lambda: markets.trending(),
    "market_summary_us": lambda: markets.market_summary(),
    "market_movers_in": lambda: markets.market_movers("all", "IN", limit=10),
    "sectors_us": lambda: markets.sectors(),
    "earnings_calendar_us": lambda: markets.earnings_calendar(),
    "market_news_us": lambda: markets_news(),
}


def markets_news():
    return news.market_news(limit=5)


def record(name):
    log = []
    real = fetch._replies

    def recording(calls, language, country, label):
        replies = real(calls, language, country, label)
        for i, (rpcid, args) in enumerate(calls):
            reply = replies.get(str(i + 1)) or (next(iter(replies.values())) if len(calls) == 1 else None)
            data = {"error": reply[2]} if reply and reply[2] is not None else (reply[1] if reply else {"error": "missing"})
            log.append([rpcid, args, language, country, data])
        return replies

    fetch._replies = recording
    try:
        SCENARIOS[name]()
    finally:
        fetch._replies = real
    os.makedirs(FX, exist_ok=True)
    with gzip.open(os.path.join(FX, f"{name}.json.gz"), "wt", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, default=str)
    print(f"recorded {name}: {len(log)} rpc calls")


if __name__ == "__main__":
    for scenario in (sys.argv[1:] or list(SCENARIOS)):
        record(scenario)
