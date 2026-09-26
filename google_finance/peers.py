"""Peers of a symbol.

  similar  SICF5d [E, N] — up to 20 listings Google considers similar (works
           for currency pairs and futures too)
  related  AYGGC [E] — the quote page's "Related stocks" card: each peer's
           quote and its latest reported quarter
"""
from google_finance import parsers
from google_finance.common import entity_batch, identity
from google_finance.shared import at

MAX_SIMILAR = 20


def similar(symbol, limit=10, language="en"):
    """Listings similar to the symbol, with live quotes."""
    q, _row, (data,) = entity_batch(symbol, lambda e: [("SICF5d", [e, MAX_SIMILAR])], language=language,
                                    label="similar")
    items = parsers.ticker_rows(data, exclude={q["symbol"]})
    out = identity(q)
    out.update({"count": min(limit, len(items)), "similar": items[:limit]})
    return out


def related(symbol, language="en"):
    """The quote page's "Related stocks": each with its quote and its latest
    reported quarter (revenue / EPS vs estimates)."""
    q, _row, (data,) = entity_batch(symbol, lambda e: [("AYGGC", [e])], language=language, label="related")
    items = []
    for entry in at(data, 0) or []:
        quote = parsers.ticker_row(at(entry, 1))
        if not quote or quote["symbol"] == q["symbol"]:
            continue
        latest = parsers.earnings_row(at(entry, 2))
        if latest:
            latest.pop("symbol", None)
            latest.pop("name", None)
        quote["latest_earnings"] = latest
        items.append(quote)
    out = identity(q)
    out.update({"count": len(items), "related": items})
    return out
