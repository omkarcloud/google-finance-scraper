"""Company fundamentals: financial statements, earnings, earnings calls and
analyst ratings (stocks; funds / ETFs / indexes / pairs have none).

  financials       Pr8h2e [[E], null, 1]  income statement, balance sheet and
                   cash flow for every quarter (AAPL: 110 quarters back to
                   1999) and fiscal year Google holds
  earnings         Kcy68c [[E], 1]        reported quarters (actual vs
                   estimate, surprise, beat / miss) + the scheduled ones
  earnings_call    Z462t [E, null, null, fiscal year, fiscal quarter, 1]
                   the call transcript (speaker-timed segments), audio and
                   documents; for the latest quarter also the AI highlights
                   and concerns (lP79gf) and the "At a glance" insights
                   from the news (elz5Ef)
  analyst_ratings  YTM9q [E]              TipRanks consensus, 12-month price
                   targets and every rating with the analyst's track record
"""
from google_finance import parsers
from google_finance.common import entity_batch, identity
from google_finance.shared import at

PERIODS = ("quarterly", "annual")


def financials(symbol, period="quarterly", limit=8, language="en"):
    """Full financial statements, newest period first."""
    q, _row, (data,) = entity_batch(symbol, lambda e: [("Pr8h2e", [[e], None, 1])], language=language,
                                    label="financials")
    quarters, annuals = parsers.financials(data)
    periods = quarters if period == "quarterly" else annuals
    out = identity(q)
    out.update({"period": period, "currency": periods[0]["currency"] if periods else None,
                "total_periods": len(periods), "count": min(limit, len(periods)), "periods": periods[:limit]})
    return out


def earnings(symbol, language="en"):
    """Every quarter Google tracks: the upcoming reports (estimates and the
    scheduled date) and the reported ones (actuals, surprise, beat / miss)."""
    q, _row, (data,) = entity_batch(symbol, lambda e: [("Kcy68c", [[e], 1])], language=language,
                                    label="earnings")
    rows = [parsers.earnings_row(r) for r in (at(data, 0) or [])]
    rows = [r for r in rows if r]
    for r in rows:
        r.pop("symbol", None)
        r.pop("name", None)
    rows.sort(key=lambda r: (r["period_end_date"] or "", r["fiscal_year"], r["fiscal_quarter"] or 0), reverse=True)
    upcoming = [r for r in rows if not r["is_reported"]]
    reported = [r for r in rows if r["is_reported"]]
    upcoming.sort(key=lambda r: (r["period_end_date"] or ""))
    out = identity(q)
    out.update({"next_report": upcoming[0] if upcoming else None, "upcoming": upcoming, "reported": reported})
    return out


def _transcript(t):
    segments = []
    for s in at(t, 3, 0) or []:
        if isinstance(s, list) and isinstance(at(s, 2), str):
            segments.append({"speaker": parsers.text(at(s, 4)), "role": parsers.text(at(s, 5)) or None,
                             "company": parsers.text(at(s, 6)) or None, "start_seconds": parsers.num(at(s, 0), 2),
                             "end_seconds": parsers.num(at(s, 1), 2), "text": parsers.text(at(s, 2))})
    return segments


DOCUMENT_KINDS = {1: "financial_report", 2: "press_release"}   # AAPL Q3 2026: 1 = the 10-Q, 2 = Exhibit 99.1


def _media(t):
    docs = []
    for d in at(t, 4) or []:
        link = at(d, 0, 2)
        if isinstance(link, str):
            docs.append({"type": DOCUMENT_KINDS.get(at(d, 1), "document"), "link": link})
    link = lambda i: at(t, i, 2) if isinstance(at(t, i, 2), str) else None  # noqa: E731
    return docs, {"hls": link(5), "mp3": link(7), "live_stream": link(8)}, {"json": link(9), "live_jsonl": link(10)}


def _highlight(h, with_title):
    if not isinstance(h, list) or not isinstance(at(h, 2), str):
        return None
    out = {"title": parsers.text(at(h, 1)) or None} if with_title else {}
    out.update({"text": parsers.text(at(h, 2)), "speaker": parsers.text(at(h, 5)),
                "role": parsers.text(at(h, 6)), "offset_seconds": parsers.num(at(h, 8))})
    if with_title:
        out.pop("speaker"), out.pop("role")
    return out


def earnings_call(symbol, fiscal_year=None, fiscal_quarter=None, language="en"):
    """An earnings call: transcript, audio, documents and (latest quarter)
    AI highlights, concerns and news insights."""
    q, _row, (call, summary, glance) = entity_batch(
        symbol, lambda e: [("Z462t", [e, None, None, fiscal_year, fiscal_quarter, 1]), ("lP79gf", [e]),
                           ("elz5Ef", [e])], language=language, label="earnings call")
    t = at(call, 0, 0) or []
    year, quarter = at(t, 1), at(t, 2)
    latest = fiscal_year is None or (fiscal_year == year and fiscal_quarter == quarter)
    if fiscal_year is not None and (year, quarter) != (fiscal_year, fiscal_quarter):
        from google_finance.fetch import FinanceNotFound
        raise FinanceNotFound(f"{q['symbol']}: no earnings call for fiscal Q{fiscal_quarter} {fiscal_year}")
    documents, audio, transcript_files = _media(t)
    segments = _transcript(t)
    out = identity(q)
    out.update({
        "fiscal_year": year,
        "fiscal_quarter": quarter,
        "has_transcript": bool(segments),
        "duration_seconds": segments[-1]["end_seconds"] if segments else None,
        "audio": audio,
        "documents": documents,
        "transcript_files": transcript_files,
        "highlights": [h for h in (_highlight(x, False) for x in at(summary, 1) or []) if h] if latest else [],
        "concerns": [h for h in (_highlight(x, True) for x in at(summary, 2) or []) if h] if latest else [],
        "at_a_glance": [p for p in (parsers.cited_point(x) for x in at(glance, 0) or []) if p] if latest else [],
        "segment_count": len(segments),
        "transcript": segments,
    })
    return out


def analyst_ratings(symbol, language="en"):
    """TipRanks analyst consensus, price targets and individual ratings."""
    q, _row, (data,) = entity_batch(symbol, lambda e: [("YTM9q", [e])], language=language,
                                    label="analyst ratings")
    summary = parsers.analyst_summary(at(data, 0))
    ratings = [r for r in (parsers.analyst_rating(x) for x in at(data, 1) or []) if r]
    out = identity(q)
    out.update({"price": q.get("price"), "currency": q.get("currency")})
    out.update(summary or {"consensus": None, "analyst_count": None, "buy_count": None, "hold_count": None,
                           "sell_count": None, "price_target": None})
    out.update({"ratings_count": len(ratings), "ratings": ratings})
    return out
