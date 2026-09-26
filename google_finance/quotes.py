"""Quotes, company details and currency conversion.

  quote     ticker row + quote head + about  -> price snapshot with the day's
            statistics
  quotes    one gCvqoe call for up to MAX_QUOTES symbols
  details   everything on the Overview tab: price, key statistics, company /
            fund / futures / currency profile, logo, TipRanks news sentiment
  convert   a currency / crypto pair quote times an amount
"""
from google_finance import fetch, parsers, symbols
from google_finance.common import entity_batch, identity

MAX_QUOTES = 25


def _snapshot(quote, row, head, about):
    stats = parsers.key_stats(row, head, about)
    out = dict(quote)
    pair = out.pop("pair", None)
    ext = out.pop("extended_hours", None)
    hours = out.pop("market_hours", None)
    mid = out.pop("google_mid", None)
    for key in ("open", "day_high", "day_low", "year_high", "year_low", "volume", "average_volume",
                "market_cap"):
        out[key] = stats[key]
    out["extended_hours"] = ext
    out["market_hours"] = hours
    out["pair"] = pair
    out["google_mid"] = mid
    return out


def quote(symbol, language="en"):
    """A live price snapshot: price, change, day and 52-week ranges, volume,
    market cap, extended-hours price and the trading session."""
    q, row, (head, about) = entity_batch(
        symbol, lambda e: [("ADgT7b", [[e], 1, 1, 1]), ("JL8oKc", [[e]])], language=language, label="quote")
    return _snapshot(q, row, parsers.quote_head(head), parsers.about_block(about))


def quotes(symbols_list, language="en"):
    """Up to MAX_QUOTES quotes in one call; unknown symbols are listed in
    `not_found` instead of failing the request."""
    resolved, not_found = [], []
    for sym, res in zip(symbols_list, _resolve_quietly(symbols_list, language)):
        if res is None:
            not_found.append(sym.lstrip(symbols.BARE_PREFIX))
        else:
            resolved.append(res)
    items = []
    if resolved:
        data = fetch.rpc("gCvqoe", [[e for _, e in resolved], 1], language=language, label="quotes")
        rows = parsers.find_rows(data)
        by_symbol = {parsers.symbol_of(r): parsers.ticker_row(r) for r in rows}
        for canonical, _ in resolved:
            item = by_symbol.get(canonical)
            if item is None and canonical.startswith("/"):
                item = next((q for q in by_symbol.values() if q.get("google_mid") == canonical), None)
            if item is None:
                not_found.append(canonical)
            else:
                items.append(item)
    return {"count": len(items), "quotes": items, "not_found": not_found}


def _resolve_quietly(symbols_list, language):
    def one(s):
        try:
            return symbols.resolve(s, language)
        except fetch.FinanceNotFound:
            return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(symbols_list)))) as pool:
        return list(pool.map(one, symbols_list))


def details(symbol, language="en"):
    """Everything the quote page's Overview tab shows."""
    q, row, (head, about, sentiment) = entity_batch(
        symbol, lambda e: [("ADgT7b", [[e], 1, 1, 1]), ("JL8oKc", [[e]]),
                           ("smi6ye", [e[1] or e[2] or e[0]] if len(e) > 1 else [e[0]])],
        language=language, label="details")
    head, about = parsers.quote_head(head), parsers.about_block(about)
    snapshot = _snapshot(q, row, head, about)
    stats = parsers.key_stats(row, head, about)
    kind = q.get("type")
    out = identity(q)
    out.update({
        "logo": parsers.logo_of(head),
        "industry": parsers.text(parsers.at(head, 18)) if head else None,
        "quote": {k: snapshot.get(k) for k in ("price", "change", "change_percent", "previous_close", "currency",
                                               "last_updated_at", "extended_hours", "market_hours", "timezone")},
        "key_stats": {k: v for k, v in stats.items() if k != "previous_close"},
        "profile": parsers.company_profile(about) if kind in ("stock", "etf", "index") else None,
        "fund": parsers.fund_profile(about) if kind == "mutual_fund" else None,
        "futures": parsers.futures_profile(about, row) if kind == "futures" else None,
        "currencies": parsers.pair_currencies(about) if kind in ("currency", "cryptocurrency") else None,
        "private_company": parsers.private_company_profile(row, about) if kind == "private_company" else None,
        "news_sentiment": parsers.news_sentiment(sentiment),
        "country": q.get("country"),
        "google_mid": q.get("google_mid"),
    })
    return out


def convert(from_currency, to_currency, amount=1.0, language="en"):
    """Convert an amount between two currencies / cryptocurrencies at
    Google Finance's live rate."""
    pair = f"{from_currency}-{to_currency}"
    q, _row, _ = entity_batch(pair, lambda e: [], language=language, label="convert")
    rate = q.get("price")
    return {
        "from_currency": from_currency,
        "to_currency": to_currency,
        "from_currency_name": (q.get("pair") or {}).get("base_currency_name"),
        "to_currency_name": (q.get("pair") or {}).get("quote_currency_name"),
        "amount": amount,
        "converted_amount": round(rate * amount, 8) if rate is not None else None,
        "exchange_rate": rate,
        "change": q.get("change"),
        "change_percent": q.get("change_percent"),
        "previous_close": q.get("previous_close"),
        "type": q.get("type"),
        "link": q.get("link"),
        "last_updated_at": q.get("last_updated_at"),
    }
