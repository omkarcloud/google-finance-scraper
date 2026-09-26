"""AI and crowd insights on one symbol.

  analysis            Ax3cwd [E] -> [[?, summary, [bullish points],
                      [bearish points]], ?, ?, ?] (points: [title, text,
                      [citation ids], [sources]]) + smi6ye TipRanks news
                      sentiment — the Overview tab's AI summary and
                      "Bullish view / Bearish view". The leading number
                      (AAPL: 78) and the three trailing fractions are not
                      rendered anywhere and are left out.
  key_moments         qsYsff [[E]] -> the chart's "Key moments": dated price
                      moves with an AI explanation, tags and news sources
  prediction_markets  qdDOU [E, null, null, null, 1] -> the "Prediction
                      market consensus" card (Kalshi / Polymarket)
"""
from google_finance import parsers
from google_finance.common import entity_batch, identity
from google_finance.shared import at, iso_date

DIRECTIONS = {1: "up", 2: "down"}


def analysis(symbol, language="en"):
    """AI-written analysis with bullish / bearish arguments (cited) and the
    TipRanks news-sentiment outlook."""
    q, _row, (data, sentiment) = entity_batch(
        symbol, lambda e: [("Ax3cwd", [e]), ("smi6ye", [e[1] or e[2]] if len(e) > 1 else [e[0]])],
        language=language, label="analysis")
    head = at(data, 0) or []
    out = identity(q)
    out.update({
        "summary": parsers.text(at(head, 1)),
        "bullish_view": [p for p in (parsers.cited_point(x) for x in at(head, 2) or []) if p],
        "bearish_view": [p for p in (parsers.cited_point(x) for x in at(head, 3) or []) if p],
        "news_sentiment": parsers.news_sentiment(sentiment),
    })
    return out


def _moment(item):
    if not isinstance(item, list) or not isinstance(at(item, 1), str):
        return None
    move = at(item, 3, 0) or []
    return {
        "date": iso_date(at(move, 0)) if isinstance(at(move, 0), list) else None,
        "title": parsers.text(at(item, 0)),
        "explanation": parsers.text(at(item, 1)),
        "direction": DIRECTIONS.get(at(item, 7)),
        "close_price": parsers.num(at(move, 1), 4),
        "change_percent": parsers.num(at(move, 2), 4),
        "tags": [t for t in (at(item, 2) or []) if isinstance(t, str)],
        "sources": [s for s in (parsers.source_ref(r) for r in at(item, 5) or []) if s],
    }


def key_moments(symbol, language="en"):
    """The chart's "Key moments": the biggest recent price moves, each with
    the AI explanation of why the stock moved and the news behind it."""
    q, _row, (data,) = entity_batch(symbol, lambda e: [("qsYsff", [[e]])], language=language,
                                    label="key moments")
    items = []
    for block in at(data, 0) or []:
        for item in at(block, 1) or []:
            m = _moment(item)
            if m:
                items.append(m)
    items.sort(key=lambda m: m["date"] or "", reverse=True)
    out = identity(q)
    out.update({"count": len(items), "moments": items})
    return out


def prediction_market(row):
    """A prediction-market ticker row -> its card."""
    base = parsers.ticker_row(row)
    if not base:
        return None
    return {
        "symbol": base["symbol"],
        "question": base.get("question") or base["name"],
        "outcome": base.get("outcome"),
        "platform": (base.get("platform") or "").title() or None,
        "probability_percent": base.get("probability_percent"),
        "probability_change": base.get("change"),
        "volume": base.get("volume"),
        "event_id": base.get("event_id"),
        "link": base["link"],
        "last_updated_at": base["last_updated_at"],
    }


def prediction_markets(symbol, language="en"):
    """Kalshi / Polymarket markets Google links to the symbol."""
    q, _row, (data,) = entity_batch(symbol, lambda e: [("qdDOU", [e, None, None, None, 1])], language=language,
                                    label="prediction markets")
    markets = [m for m in (prediction_market(r) for r in parsers.find_rows(data)) if m]
    out = identity(q)
    out.update({"count": len(markets), "markets": markets})
    return out
