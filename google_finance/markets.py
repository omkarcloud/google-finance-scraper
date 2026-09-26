"""Market-level data (no symbol): search, trending, the home page's market
summary, movers, sectors and the earnings calendar. `country` (gl) picks
the market, `language` (hl) the names.

  search            XB3kn [query, null, 1] (mKsvE [query] fallback) — the
                    search box: stocks, ETFs, funds, indexes, futures,
                    currencies, crypto and prediction markets
  trending          XB3kn ["", null, 1] — what the empty search box suggests
  market_summary    U20P6c [1] — the home page's region tabs (US, Europe,
                    Asia, India, Latin America, currencies, crypto, futures)
  market_movers     YtbmEe [[types], N, 0] (1 most active, 2 gainers, 3
                    losers) -> [gainers, losers, most active] in FIXED slots,
                    ≤ 50 each (empty until the market's first session of
                    the day)
  sectors           OsY2Qc [null, [null, 1]] — the "Equity sectors" list
  earnings_calendar HGhSgc [k, 0] — featured earnings (k: 1 upcoming,
                    2 today, 3 this week); Google serves US and CA only
"""
from google_finance import fetch, parsers, symbols
from google_finance.shared import at, iso_date

REGIONS = {1: "us", 2: "europe", 3: "asia", 4: "currencies", 5: "crypto", 7: "futures", 8: "india",
           9: "latin_america"}
MOVER_TYPES = {"most_active": 1, "gainers": 2, "losers": 3}
MOVER_SLOTS = {"gainers": 0, "losers": 1, "most_active": 2}   # reply slots are fixed, whatever order was asked
CALENDAR_PERIODS = {"upcoming": 1, "today": 2, "this_week": 3}
MAX_MOVERS = 50


def _search_result(row):
    quote = at(row, 3)
    if parsers.is_ticker_row(quote):
        item = parsers.ticker_row(quote)
        item.pop("market_hours", None)
        return item
    listing = at(quote, 1) if isinstance(quote, list) else None
    if isinstance(listing, list) and len(listing) == 2 and isinstance(at(quote, 2), str):
        symbol = f"{listing[0]}:{listing[1]}"
        return {"symbol": symbol, "ticker": listing[0], "exchange": listing[1], "name": parsers.text(at(quote, 2)),
                "type": parsers.TYPE_NAMES.get(at(quote, 3)), "link": parsers.quote_link(symbol)}
    return None


def _results(rows, limit):
    items, seen = [], set()
    for row in rows:
        item = _search_result(row)
        if item and item["symbol"] not in seen:
            seen.add(item["symbol"])
            items.append(item)
    return items[:limit]


def search(query, country="US", language="en", limit=20):
    """Google Finance search: every asset class, best match first."""
    rows = symbols.search_rows(query, language=language, country=country)
    items = _results(rows, limit)
    return {"query": query, "count": len(items), "results": items}


def trending(country="US", language="en"):
    """What Google Finance's search box suggests before typing (popular
    listings and prediction markets)."""
    data = fetch.rpc("XB3kn", ["", None, 1], language=language, country=country, label="trending")
    items = _results(at(data, 0) or [], 50)
    return {"country": country, "count": len(items), "results": items}


def market_summary(country="US", language="en"):
    """The home page's market tabs: headline indexes per region, major
    currencies, cryptocurrencies and index / commodity futures."""
    data = fetch.rpc("U20P6c", [1], language=language, country=country, label="market summary")
    regions = []
    for group in at(data, 0) or []:
        gid = at(group, 0)
        items = []
        for entry in at(group, 1) or []:
            quote = parsers.ticker_row(at(entry, 1, 0))
            if quote:
                quote["short_name"] = parsers.text(at(entry, 2))
                items.append(quote)
        if items:
            regions.append({"region": REGIONS.get(gid, f"group_{gid}"), "count": len(items), "quotes": items})
    return {"country": country, "regions": regions}


def market_movers(type="all", country="US", language="en", limit=20):
    """Most active, top gainers and top losers of a market (by `country`)."""
    wanted = list(MOVER_TYPES) if type == "all" else [type]
    data = fetch.rpc("YtbmEe", [[MOVER_TYPES[t] for t in wanted], min(limit, MAX_MOVERS), 0], language=language,
                     country=country, label="market movers")
    out = {"country": country}
    for name in wanted:
        items = parsers.ticker_rows(at(data, MOVER_SLOTS[name]))[:limit]
        for rank, item in enumerate(items, 1):
            item["rank"] = rank
        out[name] = items
    return out


def sectors(country="US", language="en"):
    """Equity sector indexes of a market with their day's move."""
    data = fetch.rpc("OsY2Qc", [None, [None, 1]], language=language, country=country, label="sectors")
    items = []
    for block in at(data, 0) or []:
        for head in at(block, 3) or []:
            quote = parsers.ticker_row(at(head, 19))
            if not quote:
                continue
            dp = at(head, 7) if isinstance(at(head, 7), int) else 2
            quote.update({"sector": parsers.text(at(head, 14)), "open": parsers.num(at(head, 2), dp) or None,
                          "day_high": parsers.num(at(head, 5), dp) or None,
                          "day_low": parsers.num(at(head, 4), dp) or None})
            quote.pop("market_hours", None)
            items.append(quote)
    return {"country": country, "count": len(items), "sectors": items}


def earnings_calendar(period="upcoming", country="US", language="en"):
    """Google Finance's featured earnings calendar (US and Canada only)."""
    data = fetch.rpc("HGhSgc", [CALENDAR_PERIODS[period], 0], language=language, country=country,
                     label="earnings calendar")
    items = []
    for row in at(data, 0) or []:
        e = parsers.earnings_row(at(row, 3))
        if not e:
            continue
        listing = at(row, 0) or []
        symbol = e.pop("symbol", None) or (f"{listing[0]}:{listing[1]}" if len(listing) == 2 else None)
        name = e.pop("name", None)
        item = {"symbol": symbol, "name": name, "link": parsers.quote_link(symbol),
                "event": parsers.text(at(row, 2)), "date": iso_date(at(row, 1)) if isinstance(at(row, 1), list) else None}
        item.update(e)
        items.append(item)
    items.sort(key=lambda x: (x["report_at"] or x["date"] or ""))
    return {"country": country, "period": period, "count": len(items), "earnings": items}
