"""News.

  news         wdVNWe [5, N, [E]] (web sources) + kA4MVd [2, N, [E]] (the
               News Corp partner feed: WSJ, Barron's, MarketWatch) — the
               quote page's "News stories", merged newest first
  market_news  the home page: D8Aqrd ["market_summary", 1] (the AI-written
               "US market summary" stories with cited sources),
               dcwbnc [N] (partner top stories with a summary) and
               wdVNWe [1, N] (the "Latest updates" feed)
"""
from google_finance import fetch, parsers
from google_finance.common import entity_batch, identity
from google_finance.shared import at

MAX_NEWS = 50


def news(symbol, limit=20, language="en"):
    """News about one symbol from web sources and Google's news partners."""
    n = max(limit, 12)
    q, _row, (web, partner) = entity_batch(
        symbol, lambda e: [("wdVNWe", [5, n, [e]]), ("kA4MVd", [2, n, [e]])], language=language, label="news")
    seen = set()
    items = parsers.news_items(at(web, 0), seen) + parsers.news_items(at(partner, 0), seen)
    items.sort(key=lambda x: x["published_at"] or "", reverse=True)
    out = identity(q)
    out.update({"count": min(limit, len(items)), "news": items[:limit]})
    return out


def _story(st):
    if not isinstance(st, list) or not isinstance(at(st, 1), str):
        return None
    sources = []
    for ref in at(st, 2) or []:
        link = at(ref, 0)
        if isinstance(link, str):
            sources.append({"title": parsers.text(at(ref, 1)), "link": link, "source": parsers.text(at(ref, 2)),
                            "source_icon": at(ref, 7) if isinstance(at(ref, 7), str) else None})
    return {"title": parsers.text(at(st, 0)), "summary": parsers.text(at(st, 1)), "sources": sources}


def _top_story(row):
    if not isinstance(row, list) or not isinstance(at(row, 4), str):
        return None
    return {"title": parsers.text(at(row, 0)), "link": at(row, 4), "source": parsers.text(at(row, 5)),
            "summary": parsers.text(at(row, 1)), "source_icon": at(row, 6) if isinstance(at(row, 6), str) else None,
            "published_at": parsers.ts(at(row, 2))}


def market_news(country="US", language="en", limit=20):
    """The home page's news: AI market-summary stories, partner top stories
    and the latest news feed for a market."""
    n = max(limit, 8)
    summary, top, latest = fetch.batch(
        [("D8Aqrd", ["market_summary", 1]), ("dcwbnc", [min(n, 30)]), ("wdVNWe", [1, n])],
        language=language, country=country, strict=False, label="market news")
    stories = [s for s in (_story(x) for x in at(fetch.ok(summary), 0) or []) if s]
    top_stories = [s for s in (_top_story(x) for x in at(fetch.ok(top), 0) or []) if s]
    latest_news = parsers.news_items(at(fetch.ok(latest), 0))
    return {
        "country": country,
        "market_summary": stories,
        "top_stories": top_stories[:limit],
        "latest_news": latest_news[:limit],
    }
