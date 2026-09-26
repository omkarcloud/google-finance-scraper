"""Pure parsers for Google Finance's positional rpc arrays (no network).

Every function takes the decoded rpc data (or one row of it) and returns
plain dicts; none raises on a partial / reshaped payload — a missing
index reads as None. Index maps were verified 2026-09-26 against the
rendered page (labels) and company filings (values); see the notes on
each parser.

Shared row shapes:

  ticker row   [0 mid, 1 [TICKER, EXCH] | null, 2 name, 3 type code,
                4 currency, 5 [price, change, change_pct, dp, dp, dp],
                7 previous close, 9 country, 11 [updated ts], 12 timezone,
                13 utc offset s, 15 pair descriptor, 16 [ext price,
                change, pct], 17 [regular close ts], 18 [ext ts],
                19 [[1, open dt, close dt]] session, 21 "SYM:EXCH",
                23 underlying mid (futures), 28 [markets] (prediction
                events), 29 outcome label, 30 ?, 31 volume (prediction)]
  pair         [base, quote, base name, quote name, base mid, quote mid,
                kind (1 currency, 2 crypto)]
  entity       [null, [TICKER, EXCH]] | [null, null, [BASE, QUOTE]] | [mid]
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google_finance.shared import at, clean_text, iso_date, iso_from_ts, to_int  # noqa: E402

SITE = "https://www.google.com"

TYPE_NAMES = {0: "stock", 1: "index", 2: "mutual_fund", 3: "currency", 4: "futures", 5: "etf",
              7: "prediction_event", 8: "prediction_market", 10: "prediction_event", 11: "private_company"}


# ---- value helpers ---------------------------------------------------------------------------

def num(value, decimals=None):
    """A number (int stays int), rounded to `decimals` when given; None for
    anything non-numeric. Strips float32 noise like 5.149994 -> 5.15."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, int):
        return value
    if decimals is not None:
        value = round(value, decimals)
        return int(value) if decimals == 0 else value
    return round(value, 6)


def pct(fraction, decimals=4):
    """0.0674 -> 6.74 (percent)."""
    value = num(fraction)
    return None if value is None else round(value * 100, decimals)


def text(value):
    return clean_text(value) if isinstance(value, str) else None


def ts(value):
    """[unix] or unix -> ISO-8601 UTC."""
    if isinstance(value, list):
        value = at(value, 0)
    return iso_from_ts(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def local_datetime(parts):
    """Google's [y, m, d, h, mi, s, null, [utc offset s]] -> ISO with offset
    ('2026-09-25T09:30:00-04:00'); a date-only array -> 'YYYY-MM-DD'."""
    if not isinstance(parts, list) or len(parts) < 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except (TypeError, ValueError):
        return None
    if len(parts) < 4 or parts[3] is None:
        return f"{y:04d}-{m:02d}-{d:02d}"
    h, mi, s = int(at(parts, 3) or 0), int(at(parts, 4) or 0), int(at(parts, 5) or 0)
    offset = at(parts, 7, 0)
    try:
        tz = timezone(timedelta(seconds=int(offset))) if offset is not None else timezone.utc
        return datetime(y, m, d, h, mi, s, tzinfo=tz).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def mdy_to_iso(value):
    """'09/22/2026' -> '2026-09-22'."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def quote_link(symbol):
    return f"{SITE}/finance/quote/{symbol}" if symbol else None


# ---- entities / symbols ------------------------------------------------------------------------

def pair_info(descriptor):
    """Pair descriptor -> {base_currency, base_currency_name, quote_currency, quote_currency_name}."""
    if not isinstance(descriptor, list) or len(descriptor) < 2 or not isinstance(descriptor[0], str):
        return None
    return {"base_currency": descriptor[0], "base_currency_name": at(descriptor, 2),
            "quote_currency": descriptor[1], "quote_currency_name": at(descriptor, 3)}


def pair_type(descriptor):
    return "cryptocurrency" if at(descriptor, 6) == 2 else "currency"


def symbol_of(row):
    """Canonical symbol of a ticker row: 'AAPL:NASDAQ' / 'USD-INR' / 'ID:KALSHI'."""
    if not isinstance(row, list):
        return None
    if isinstance(at(row, 21), str):
        return row[21]
    pair = at(row, 15)
    if isinstance(pair, list) and len(pair) >= 2:
        return f"{pair[0]}-{pair[1]}"
    ticker = at(row, 1)
    if isinstance(ticker, list) and len(ticker) == 2:
        return f"{ticker[0]}:{ticker[1]}"
    return None


def type_of(row):
    code = at(row, 3)
    if code == 3:
        return pair_type(at(row, 15))
    return TYPE_NAMES.get(code) if isinstance(code, int) else None


def is_ticker_row(row):
    """A ticker row: mid-or-null at [0], name at [2], int type at [3]."""
    return (isinstance(row, list) and len(row) > 11 and isinstance(at(row, 2), str)
            and isinstance(row[3], int) and (isinstance(row[1], list) or row[1] is None))


def not_found(data):
    """gCvqoe's answer for an unknown symbol is [[[null, [5]]]]."""
    return not data or (at(data, 0, 0, 1) == [5]) or not any(is_ticker_row(r) for r in (at(data, 0, 0) or []))


# ---- the ticker row -----------------------------------------------------------------------------

def _decimals(row, i, default=4):
    d = at(row, 5, 3 + i)
    return d if isinstance(d, int) and 0 <= d <= 8 else default


def _session(row):
    for s in at(row, 19) or []:
        if isinstance(s, list) and at(s, 0) == 1:
            return {"opens_at": local_datetime(at(s, 1)), "closes_at": local_datetime(at(s, 2))}
    return None


def _extended(row):
    ext = at(row, 16)
    if not isinstance(ext, list) or at(ext, 0) is None:
        return None
    updated = at(row, 18, 0)
    session = None
    for s in at(row, 19) or []:
        opens = local_datetime(at(s, 1)) if isinstance(s, list) else None
        if opens and isinstance(updated, (int, float)):
            try:
                session = "pre_market" if updated < datetime.fromisoformat(opens).timestamp() else "after_hours"
            except ValueError:
                session = None
            break
    dp = at(ext, 3) if isinstance(at(ext, 3), int) else _decimals(row, 0)
    return {"session": session, "price": num(at(ext, 0), dp), "change": num(at(ext, 1), dp),
            "change_percent": num(at(ext, 2), 4), "updated_at": ts(updated)}


def ticker_row(row):
    """The recurring ticker row -> a quote summary (every list uses it)."""
    if not is_ticker_row(row):
        return None
    symbol = symbol_of(row)
    kind = type_of(row)
    listing = at(row, 1) if isinstance(at(row, 1), list) else None
    pair = pair_info(at(row, 15))
    price = at(row, 5) if isinstance(at(row, 5), list) else []
    out = {
        "symbol": symbol,
        "ticker": at(listing, 0) if listing else (pair or {}).get("base_currency"),
        "exchange": at(listing, 1) if listing else None,
        "name": text(at(row, 2)),
        "type": kind,
        "link": quote_link(symbol),
        "price": num(at(price, 0), _decimals(row, 0)),
        "change": num(at(price, 1), _decimals(row, 1)),
        "change_percent": num(at(price, 2), 4),
        "previous_close": num(at(row, 7), _decimals(row, 0)),
        "currency": at(row, 4) or (pair or {}).get("quote_currency"),
        "country": at(row, 9),
        "timezone": at(row, 12),
        "last_updated_at": ts(at(row, 11)),
        "extended_hours": _extended(row),
        "market_hours": _session(row),
        "pair": pair,
        "google_mid": at(row, 0) if isinstance(at(row, 0), str) else None,
    }
    if kind in ("prediction_market", "prediction_event"):
        out.update(prediction_fields(row))
    elif kind == "private_company":
        out["private_company"] = private_company_fields(row)
    return out


def private_company_fields(row):
    """A private company (Crunchbase-sourced, type 11): [38] legal name,
    [39] ownership, [40] categories, [41] total funding (USD), [42] funding
    summary, [48] logo. ([44]-[47], [50], [51] are unlabelled scores.)"""
    categories = at(row, 40)
    return {"legal_name": text(at(row, 38)), "ownership": text(at(row, 39)),
            "categories": [c for c in categories if isinstance(c, str)] if isinstance(categories, list) else [],
            "total_funding": num(at(row, 41), 0), "total_funding_currency": "USD" if at(row, 41) else None,
            "funding_summary": text(at(row, 42)),
            "logo": at(row, 48) if isinstance(at(row, 48), str) and at(row, 48).startswith("http") else None}


_EMPLOYEE_RANGE = re.compile(r"Employee Range:\s*c_(\d+)_(\d+|max)", re.I)


def private_company_profile(row, about):
    """Details of a private company: the row's funding facts + the about
    block's description (about[3] {"73": text}) and Crunchbase employee
    range (about[2] "Employee Range: c_01001_05000")."""
    out = private_company_fields(row)
    about = about or []
    desc = at(about, 3)
    out["description"] = text(next(iter(desc.values()), None)) if isinstance(desc, dict) and desc else None
    m = _EMPLOYEE_RANGE.search(at(about, 2) or "") if isinstance(at(about, 2), str) else None
    out["employees_min"] = int(m.group(1)) if m else None
    out["employees_max"] = int(m.group(2)) if m and m.group(2).isdigit() else None
    return out


def prediction_fields(row):
    """Extra fields of a prediction-market row (Kalshi / Polymarket): the
    price is the YES probability in percent."""
    listing = at(row, 1) or []
    return {"platform": at(listing, 1), "question": text(at(row, 2)), "outcome": text(at(row, 29)),
            "probability_percent": num(at(row, 5, 0), 2), "volume": num(at(row, 31)),
            "event_id": at(row, 35, 0)}


def find_rows(data, depth=0, out=None):
    """Every ticker row anywhere inside a block (document order)."""
    if out is None:
        out = []
    if depth > 9 or not isinstance(data, list):
        return out
    if is_ticker_row(data):
        out.append(data)
        return out
    for item in data:
        find_rows(item, depth + 1, out)
    return out


def ticker_rows(data, exclude=()):
    """Every ticker row inside `data` -> quote summaries, deduped by symbol."""
    seen, out = set(exclude), []
    for row in find_rows(data):
        item = ticker_row(row)
        if item and item["symbol"] not in seen:
            seen.add(item["symbol"])
            out.append(item)
    return out


# ---- quote head (ADgT7b) + about (JL8oKc) -------------------------------------------------------
# quote head: [0 entity, 2 open, 3 mid, 4 low, 5 high, 6 price, 8 change,
#   10 change %, 12 currency, 13 symbol, 14 name, 15 previous close,
#   16 market cap, 17 volume, 18 industry, 19 ticker row,
#   36 / 37 [null, null, logo data URI] (light / dark)]  — verified against
#   the rendered "Open / High / Low" values (SPY, ESW00, AAPL).
# about: [0 mid, 1 short name, 2 description, 3 hq [city, region, country,
#   cc, street], 4 founded / inception [y,m,d], 5 CEO, 6 employees,
#   7 market cap, 8 previous close, 9 open, 10 high, 11 low, 12 52w high,
#   13 52w low, 14 volume, 15 currency, 16 P/E, 17 dividend yield %,
#   18 avg volume, 19 EPS, 20 beta, 21 shares outstanding, 24 exchange,
#   30 wikipedia, 31 fund inception, 32 expense ratio %, 33 category,
#   34 Morningstar rating, 35 net assets, 36 currency, 37 as-of,
#   40 yield %, 41 as-of, 44 / 45 pair currencies [code, name, description,
#   wikipedia], 53 futures segment, 54 settlement, 56 open interest,
#   70 ex-dividend date, 71 industry]

def quote_head(data):
    head = at(data, 0, 0)
    return head if isinstance(head, list) and isinstance(at(head, 0), list) else None


def about_block(data):
    head = at(data, 0, 0)
    return head if isinstance(head, list) and len(head) >= 3 else None


def _is_real(v):
    """Google reports 0 for 'not applicable' open/high/low (funds, FX)."""
    return v not in (None, 0)


def key_stats(row, head, about):
    """Price statistics from the ticker row, quote head and about block."""
    head = head or []
    about = about or []
    dp = _decimals(row, 0) if row else 2
    first = lambda *vals: next((v for v in vals if _is_real(v)), None)  # noqa: E731
    ex_div = at(about, 70)
    futures = at(row, 3) == 4 if row else False   # futures repeat the day's range in the 52-week slots
    return {
        "open": num(first(at(head, 2), at(about, 9)), dp),
        "day_high": num(first(at(head, 5), at(about, 10)), dp),
        "day_low": num(first(at(head, 4), at(about, 11)), dp),
        "previous_close": num(first(at(row, 7) if row else None, at(head, 15), at(about, 8)), dp),
        "year_high": None if futures else num(at(about, 12), dp),
        "year_low": None if futures else num(at(about, 13), dp),
        "volume": num(first(at(head, 17), at(about, 14))),
        "average_volume": num(at(about, 18)),
        "market_cap": num(first(at(head, 16), at(about, 7)), 0),
        "pe_ratio": num(at(about, 16), 2),
        "eps": num(at(about, 19), 4),
        "dividend_yield_percent": num(at(about, 17), 4),
        "ex_dividend_date": iso_date(ex_div) if isinstance(ex_div, list) else None,
        "beta": num(at(about, 20), 4),
        "shares_outstanding": num(at(about, 21), 0),
        "primary_exchange": at(about, 24) if isinstance(at(about, 24), str) else None,
    }


def company_profile(about):
    """Company facts (stocks; ETFs carry description + inception only)."""
    if not about:
        return None
    hq = at(about, 3) if isinstance(at(about, 3), list) else None
    founded = at(about, 4)
    website = next((x for x in about if isinstance(x, str) and x.startswith("http") and "wikipedia.org" not in x), None)
    out = {
        "name": text(at(about, 1)),
        "description": text(at(about, 2)),
        "ceo": text(at(about, 5)) if isinstance(at(about, 5), str) else None,
        "employees": num(at(about, 6)) if isinstance(at(about, 5), str) or hq else None,
        "founded_date": iso_date(founded) if isinstance(founded, list) else None,
        "industry": text(at(about, 71)),
        "headquarters": ({"street": at(hq, 4), "city": at(hq, 0), "region": at(hq, 1), "country": at(hq, 2),
                          "country_code": at(hq, 3)} if hq else None),
        "website": website,
        "wikipedia_link": at(about, 30) if isinstance(at(about, 30), str) else None,
    }
    return out if any(v for k, v in out.items() if k != "name") else None


def fund_profile(about):
    """Mutual-fund facts (MUTF listings)."""
    if not about or at(about, 32) is None and at(about, 35) is None and at(about, 33) is None:
        return None
    return {
        "category": text(at(about, 33)),
        "inception_date": iso_date(at(about, 31)) if isinstance(at(about, 31), list) else None,
        "expense_ratio_percent": num(at(about, 32), 4),
        "net_assets": num(at(about, 35), 0),
        "net_assets_currency": at(about, 36) if isinstance(at(about, 36), str) else None,
        "net_assets_as_of": iso_date(at(about, 37)) if isinstance(at(about, 37), list) else None,
        "yield_percent": num(at(about, 40), 4),
        "yield_as_of": iso_date(at(about, 41)) if isinstance(at(about, 41), list) else None,
        "morningstar_rating": num(at(about, 34)),
    }


def futures_profile(about, row):
    """Futures-contract facts."""
    if not about or (at(about, 54) is None and at(about, 56) is None and at(about, 53) is None):
        return None
    return {
        "market_segment": at(about, 53) if isinstance(at(about, 53), str) else None,
        "settlement_price": num(at(about, 54), 4),
        "open_interest": num(at(about, 56)),
        "underlying_google_mid": at(row, 23) if row and isinstance(at(row, 23), str) else None,
    }


def pair_currencies(about):
    """FX / crypto page: both legs with their descriptions."""
    out = []
    for i in (44, 45):
        leg = at(about, i)
        if isinstance(leg, list) and isinstance(at(leg, 0), str):
            out.append({"code": leg[0], "name": text(at(leg, 1)), "description": text(at(leg, 2)),
                        "wikipedia_link": next((x for x in leg[3:] if isinstance(x, str) and x.startswith("http")), None)})
    return out or None


def logo_of(head):
    """The light-theme logo (an inline SVG data URI) from the quote head."""
    for i in (36, 37):
        uri = at(head, i, 2)
        if isinstance(uri, str) and uri.startswith("data:image"):
            return uri
    return None


# ---- outlook (smi6ye) ---------------------------------------------------------------------------
# [null, null, [[TICKER, EXCH], bullish, neutral, bearish, net score,
#   sector bullish, sector neutral, sector bearish, sector net score,
#   weekly average articles, articles last week, buzz ratio]] — rendered as
#   "Outlook: From TipRanks news sentiment reports".

def news_sentiment(data):
    s = at(data, 2)
    if not isinstance(s, list) or len(s) < 5 or not isinstance(at(s, 1), (int, float)):
        return None
    if all((at(s, i) or 0) == 0 for i in (1, 2, 3)):
        return None
    return {
        "source": "TipRanks news sentiment",
        "bullish_percent": pct(at(s, 1), 2),
        "neutral_percent": pct(at(s, 2), 2),
        "bearish_percent": pct(at(s, 3), 2),
        "score": num(at(s, 4), 2),
        "sector_average": {"bullish_percent": pct(at(s, 5), 2), "neutral_percent": pct(at(s, 6), 2),
                           "bearish_percent": pct(at(s, 7), 2), "score": num(at(s, 8), 2)},
        "articles_last_week": num(at(s, 10)),
        "weekly_average_articles": num(at(s, 9), 2),
        "buzz_ratio": num(at(s, 11), 4),
    }


# ---- charts (c2u4wc) ----------------------------------------------------------------------------
# [[series…]] series = [entity pair | null, mid, currency, [segments], null,
#   utc offset, last price, name, interval s, type code, pair descriptor]
# segment = [[kind (1 regular, 3 after hours), start, end], line points,
#   candles]; line point = [[y,m,d,h,mi,s,null,[off]], [close, change,
#   change fraction, …], volume]; candle = [open, close, high, low,
#   "ISO time", volume] (the 16:00 AAPL candle of 2026-09-23 closes at the
#   official 337.02, so [1] is the close).

SESSION_KINDS = {1: "regular", 3: "after_hours", 2: "pre_market"}


def chart_series(series):
    if not isinstance(series, list):
        return None
    listing = at(series, 0) if isinstance(at(series, 0), list) else None
    pair = pair_info(at(series, 10))
    symbol = f"{listing[0]}:{listing[1]}" if listing else (f"{pair['base_currency']}-{pair['quote_currency']}" if pair else None)
    points, candles = [], []
    for seg in at(series, 3) or []:
        session = SESSION_KINDS.get(at(seg, 0, 0), "regular")
        for p in at(seg, 1) or []:
            values = at(p, 1) or []
            points.append({"time": local_datetime(at(p, 0)), "price": num(at(values, 0), 6),
                           "change": num(at(values, 1), 6), "change_percent": pct(at(values, 2)),
                           "volume": num(at(p, 2)), "session": session})
        for c in at(seg, 2) or []:
            if isinstance(c, list) and len(c) >= 5:
                candles.append({"time": at(c, 4), "open": num(at(c, 0), 6), "high": num(at(c, 2), 6),
                                "low": num(at(c, 3), 6), "close": num(at(c, 1), 6), "volume": num(at(c, 5)),
                                "session": session})
    return {
        "symbol": symbol,
        "name": text(at(series, 7)),
        "type": TYPE_NAMES.get(at(series, 9)) if at(series, 9) != 3 else pair_type(at(series, 10)),
        "currency": at(series, 2) if isinstance(at(series, 2), str) else (pair or {}).get("quote_currency"),
        "interval_seconds": num(at(series, 8)),
        "last_price": num(at(series, 6), 6),
        "google_mid": at(series, 1) if isinstance(at(series, 1), str) else None,
        "points": points,
        "candles": candles,
    }


def chart(data):
    return [s for s in (chart_series(x) for x in (at(data, 0) or [])) if s]


# ---- news rows (wdVNWe / kA4MVd) ----------------------------------------------------------------
# [0 link, 1 title, 2 source, 3 thumbnail (a favicon when none), 4 published
#  ts, 7 favicon, 9 [related mids], 10 story id, 12 thumb w, 13 thumb h,
#  16 snippet]

def news_item(row):
    link = at(row, 0)
    if not (isinstance(link, str) and link.startswith("http") and isinstance(at(row, 1), str)):
        return None
    thumb = at(row, 3)
    snippet = at(row, 16) if isinstance(at(row, 16), str) else None
    if snippet is None:
        snippet = next((x for x in row[8:] if isinstance(x, str) and len(x) > 60 and not x.startswith("http")), None)
    return {
        "title": text(at(row, 1)),
        "link": link,
        "source": text(at(row, 2)),
        "snippet": text(snippet),
        "thumbnail": thumb if isinstance(thumb, str) and "faviconV2" not in thumb else None,
        "source_icon": at(row, 7) if isinstance(at(row, 7), str) else None,
        "published_at": ts(at(row, 4)),
    }


def news_items(rows, seen=None):
    seen = set() if seen is None else seen
    out = []
    for row in rows or []:
        item = news_item(row) if isinstance(row, list) else None
        if item and item["link"] not in seen:
            seen.add(item["link"])
            out.append(item)
    return out


def source_ref(ref):
    """Cited source [title, snippet, link, favicon, null, source name, citation id]."""
    link = at(ref, 2)
    if not isinstance(link, str):
        return None
    return {"title": text(at(ref, 0)), "snippet": text(at(ref, 1)), "link": link, "source": text(at(ref, 5)),
            "source_icon": at(ref, 3) if isinstance(at(ref, 3), str) else None}


def cited_point(point):
    """[title, text, [citation ids], [sources]] -> {title, text, sources}."""
    if not isinstance(point, list) or not isinstance(at(point, 1), str):
        return None
    return {"title": text(at(point, 0)), "text": text(at(point, 1)),
            "sources": [s for s in (source_ref(r) for r in at(point, 3) or []) if s]}


# ---- earnings rows (Kcy68c / HGhSgc) ------------------------------------------------------------
# [0 mid, 1 [TICKER, EXCH], 2 name, 3 fiscal year, 4 fiscal quarter,
#  9 V, 10 status (2 latest, 5 past, 4 scheduled, 0 unscheduled),
#  11 [report ts], 12 date confirmed flag]
# V = [0 revenue, 2 EPS (diluted, as reported), 8 revenue estimate,
#  9 EPS (the one compared with the estimate), 10 EPS estimate,
#  11 revenue surprise (fraction), 12 EPS surprise (fraction),
#  13 result (1 beat, 2 miss, 3 mixed), 16 currency, 17 period end]

RESULTS = {1: "beat", 2: "miss", 3: "mixed"}


def earnings_row(row):
    if not isinstance(row, list) or not isinstance(at(row, 3), int):
        return None
    v = at(row, 9) or []
    eps_actual = at(v, 9) if at(v, 9) is not None else at(v, 2)
    reported = at(v, 0) is not None or eps_actual is not None
    listing = at(row, 1) or []
    return {
        "symbol": f"{listing[0]}:{listing[1]}" if len(listing) == 2 else None,
        "name": text(at(row, 2)),
        "fiscal_year": at(row, 3),
        "fiscal_quarter": at(row, 4),
        "period_end_date": iso_date(at(v, 17)) if isinstance(at(v, 17), list) else None,
        "report_at": ts(at(row, 11)),
        "is_reported": reported,
        "is_date_confirmed": bool(at(row, 12)) if at(row, 11) else False,
        "currency": at(v, 16) if isinstance(at(v, 16), str) else None,
        "eps": {"actual": num(eps_actual, 4), "estimate": num(at(v, 10), 4),
                "surprise_percent": pct(at(v, 12), 2)},
        "revenue": {"actual": num(at(v, 0), 0), "estimate": num(at(v, 8), 0),
                    "surprise_percent": pct(at(v, 11), 2)},
        "result": RESULTS.get(at(v, 13)) if reported else None,
    }


# ---- financial statements (Pr8h2e) ---------------------------------------------------------------
# data[0][0] = [quarters, annuals, …, mid, name, [TICKER, EXCH]]
#   quarter = [fiscal year, fiscal quarter, V, V of the year-earlier quarter]
#   annual  = [fiscal year, V, V of the prior year]
# V (105-106 slots; periods older than the statements carry 18) is labelled
# below from the rendered Financials tab (Income statement / Balance sheet /
# Cash flow) and Apple's FY2024 10-K; ties resolved on MSFT, JPM, DUK, CAT,
# IBM and COST. Percent fields are already percent.

INCOME_STATEMENT = [
    ("revenue", 0), ("cost_of_revenue", 7), ("cost_of_goods_sold", 105), ("gross_profit", 104),
    ("research_and_development_expenses", 39), ("selling_general_and_admin_expenses", 40),
    ("operating_expense", 38), ("total_operating_expenses", 19), ("operating_income", 4),
    ("other_non_operating_income", 43), ("interest_and_investment_income", 46), ("interest_expense", 45),
    ("net_interest_expense", 47), ("depreciation_and_amortization", 41), ("gain_loss_on_asset_sale", 44),
    ("other_operating_expenses", 42), ("ebt_including_unusual_items", 48), ("ebt_excluding_unusual_items", 49),
    ("income_tax_expense", 50), ("effective_tax_rate_percent", 21), ("net_income", 1),
    ("net_profit_margin_percent", 3), ("ebitda", 20), ("eps", 9), ("eps_basic", 51), ("eps_diluted", 2),
]
BALANCE_SHEET = [
    ("cash_and_equivalents", 37), ("short_term_investments", 56), ("cash_and_short_term_investments", 22),
    ("total_receivables", 52), ("inventory", 54), ("prepaid_expenses", 55), ("current_deferred_tax_assets", 62),
    ("total_other_current_assets", 57), ("total_current_assets", 24),
    ("net_property_plant_and_equipment", 58), ("goodwill", 59), ("other_intangibles", 60),
    ("long_term_investments", 61), ("long_term_deferred_tax_assets", 63),
    ("non_current_deferred_tax_assets", 64), ("total_other_long_term_assets", 65), ("total_assets", 23),
    ("accounts_payable", 66), ("short_term_borrowings", 67), ("accrued_expenses", 68),
    ("current_portion_of_long_term_debt", 69), ("current_income_taxes_payable", 70),
    ("current_unearned_revenue", 71), ("current_portion_of_leases", 72), ("total_current_liabilities", 36),
    ("long_term_debt", 74), ("long_term_leases", 76), ("deferred_charges_long_term", 75),
    ("pension_and_post_retirement_benefits", 77), ("non_current_unearned_revenue", 78),
    ("other_non_current_liabilities", 79), ("total_liabilities", 26), ("total_common_equity", 80),
    ("retained_earnings", 81), ("treasury_stock", 82), ("comprehensive_income_and_other", 83),
    ("additional_paid_in_capital", 84), ("minority_interest", 85), ("total_equity", 25),
    ("tangible_book_value", 86), ("shares_outstanding", 27), ("book_value_per_share", 33),
    ("price_to_book", 35), ("return_on_assets_percent", 34), ("return_on_capital_percent", 18),
    ("return_on_equity_percent", 87),
]
CASH_FLOW = [
    ("net_income", 1), ("cash_from_operations", 28), ("change_in_inventories", 89),
    ("gain_loss_on_sale_of_assets", 90), ("gain_loss_on_sale_of_investments", 91),
    ("cash_from_investing", 29), ("capital_expenditure", 103), ("cash_acquisitions", 88),
    ("sale_purchase_of_intangible_assets", 92), ("net_change_in_loans_originated", 93),
    ("short_term_debt_issued", 94), ("short_term_debt_repaid", 95), ("issuance_of_common_stock", 96),
    ("repurchase_of_common_stock", 97), ("common_dividends_paid", 98), ("special_dividend_paid", 99),
    ("total_dividends_paid", 100), ("foreign_exchange_adjustments", 101), ("cash_from_financing", 30),
    ("net_change_in_cash", 5), ("free_cash_flow", 31), ("unlevered_free_cash_flow", 102),
]
_RATIO_KEYS = {"effective_tax_rate_percent", "net_profit_margin_percent", "price_to_book",
               "return_on_assets_percent", "return_on_capital_percent", "return_on_equity_percent",
               "eps", "eps_basic", "eps_diluted", "book_value_per_share"}
_STATEMENT_SLOTS = {i for _, i in INCOME_STATEMENT + BALANCE_SHEET + CASH_FLOW} - {1}


def _statement(v, fields):
    return {key: num(at(v, i), 4 if key in _RATIO_KEYS else 0) for key, i in fields}


def financial_period(v, fiscal_year, fiscal_quarter):
    """One statement vector -> a period, or None when it carries no statements."""
    if not isinstance(v, list) or not any(at(v, i) is not None for i in _STATEMENT_SLOTS):
        return None
    return {
        "fiscal_year": fiscal_year,
        "fiscal_quarter": fiscal_quarter,
        "period_end_date": iso_date(at(v, 17)) if isinstance(at(v, 17), list) else None,
        "currency": at(v, 16) if isinstance(at(v, 16), str) else None,
        "income_statement": _statement(v, INCOME_STATEMENT),
        "balance_sheet": _statement(v, BALANCE_SHEET),
        "cash_flow": _statement(v, CASH_FLOW),
    }


def financials(data):
    """-> (quarterly periods, annual periods), newest first."""
    parts = at(data, 0, 0) or []
    quarters, annuals = [], []
    for q in at(parts, 0) or []:
        period = financial_period(at(q, 2), at(q, 0), at(q, 1)) if isinstance(q, list) else None
        if period:
            quarters.append(period)
    for a in at(parts, 1) or []:
        period = financial_period(at(a, 1), at(a, 0), None) if isinstance(a, list) else None
        if period:
            annuals.append(period)
    key = lambda p: (p["period_end_date"] or "", p["fiscal_year"] or 0, p["fiscal_quarter"] or 0)  # noqa: E731
    return sorted(quarters, key=key, reverse=True), sorted(annuals, key=key, reverse=True)


# ---- analyst ratings (YTM9q, TipRanks) ------------------------------------------------------------
# summary [0 name, 1 currency, 2 target low, 3 target high, 4 target
#  average, 5 upside %, 6 analysts, 7 consensus, 8 buy, 9 sell, 10 hold]
#  — the buy / sell / hold order is confirmed by the rendered "Buy 15 · Hold
#  11 · Sell 4" for 15, 4, 11.
# rating [0 id, 1 analyst, 2 firm, 3 rating, 4 MM/DD/YYYY, 5 link, 6 photo,
#  7 rank, 8 ranked analysts, 9 success rate, 10 average return %,
#  11 ratings, 12 successful ratings, 13 stars, 14 success rate on this
#  stock, 15 average return on this stock %, 16 headline, 17 author,
#  19 price target, 21 currency, 25 slug, 26 published, 27 action,
#  28 ratings on this stock, 29 successful ratings on this stock]

def _plain_iso(value):
    """'2026-09-23T08:50:24.9' -> '2026-09-23T08:50:24' (TipRanks timestamps)."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    return value.split(".")[0]


def analyst_summary(head):
    if not isinstance(head, list) or len(head) < 8:
        return None
    return {
        "consensus": text(at(head, 7)),
        "analyst_count": num(at(head, 6)),
        "buy_count": num(at(head, 8)),
        "hold_count": num(at(head, 10)),
        "sell_count": num(at(head, 9)),
        "price_target": {"low": num(at(head, 2), 4), "average": num(at(head, 4), 4), "high": num(at(head, 3), 4),
                         "upside_percent": num(at(head, 5), 2), "currency": at(head, 1)},
    }


def analyst_rating(r):
    if not isinstance(r, list) or not isinstance(at(r, 1), str):
        return None
    target = at(r, 19)
    return {
        "analyst": text(at(r, 1)),
        "firm": text(at(r, 2)),
        "rating": text(at(r, 3)),
        "action": text(at(r, 27)),
        "price_target": num(target, 4) if target else None,
        "currency": (at(r, 21) or None) if target else None,
        "date": mdy_to_iso(at(r, 4)),
        "article": ({"title": text(at(r, 16)), "author": text(at(r, 17)), "link": at(r, 5),
                     "published_at": _plain_iso(at(r, 26))}
                    if isinstance(at(r, 5), str) else None),
        "analyst_stats": {
            "rank": num(at(r, 7)) or None,
            "ranked_analysts": num(at(r, 8)) or None,
            "stars": num(at(r, 13), 1),
            "success_rate_percent": pct(at(r, 9), 2),
            "average_return_percent": num(at(r, 10), 2),
            "total_ratings": num(at(r, 11)),
            "successful_ratings": num(at(r, 12)),
        },
        "stock_stats": {
            "success_rate_percent": pct(at(r, 14), 2),
            "average_return_percent": num(at(r, 15), 2),
            "total_ratings": num(at(r, 28)),
            "successful_ratings": num(at(r, 29)),
        },
    }


# ---- insiders & politicians (K5Y6Xb) --------------------------------------------------------------
# data = [0 politician holdings, 1 politician trades, 2, 3, 4 insider
#   transactions, 5, 6 holdings cursor, 7 trades cursor, 8 insider cursor]
# insider [0 [TICKER, EXCH], 2 name, 4 position, 5 photo file, 6 TipRanks
#   insider rank (unlabelled), 7 classification ("Discretionary sell"),
#   8 TipRanks transaction code (S, AS, NB, NS),
#   9 [y,m,d], 10 value, 11 shares, 12 currency, 13 Form 4 link]
# trade [0 id, 1 transaction date, 2 ticker, 3 Buy/Sell, 4 amount range,
#   5 disclosure date, 6 full name, 7 name, 8 chamber, 9 party,
#   10 district, 11 owner]
# holding [0 id, 1 owner, 2 ticker, 3 asset type, 4 ticker, 5 disclosure
#   year, 6 / 7 / 8 shares (mid, min, max — the rendered "Shares (min.) /
#   (mid.) / (max.)" columns), 9 name, 10 is current,
#   11 first name, 12 last name, 13 gender, 14 chamber, 15 party,
#   16 district]

def insider_transaction(r):
    if not isinstance(r, list) or not isinstance(at(r, 2), str):
        return None
    classification = text(at(r, 7))
    return {
        "insider": text(at(r, 2)),
        "position": text(at(r, 4)),
        "transaction_type": ("buy" if classification and classification.lower().endswith("buy") else
                             "sell" if classification and classification.lower().endswith("sell") else None),
        "classification": classification,
        "transaction_code": at(r, 8) if isinstance(at(r, 8), str) else None,
        "date": iso_date(at(r, 9)) if isinstance(at(r, 9), list) else None,
        "shares": num(at(r, 11)),
        "value": num(at(r, 10), 2),
        "currency": at(r, 12) if isinstance(at(r, 12), str) else None,
        "sec_filing_link": at(r, 13) if isinstance(at(r, 13), str) else None,
    }


def _amount_range(value):
    """'$1,001 - $15,000' -> (1001, 15000)."""
    if not isinstance(value, str):
        return None, None
    parts = [to_int(p) for p in value.replace("–", "-").split("-")]
    parts = [p for p in parts if p is not None]
    if not parts:
        return None, None
    return parts[0], (parts[1] if len(parts) > 1 else None)


def _politician(r, name_i, full_i, chamber_i, party_i, district_i):
    return {"name": text(at(r, name_i)), "full_name": text(at(r, full_i)), "chamber": text(at(r, chamber_i)),
            "party": text(at(r, party_i)), "district": text(at(r, district_i)) or None}


def politician_trade(r):
    if not isinstance(r, list) or not isinstance(at(r, 1), str):
        return None
    low, high = _amount_range(at(r, 4))
    return {
        "politician": _politician(r, 7, 6, 8, 9, 10),
        "transaction_type": (at(r, 3) or "").lower() or None,
        "transaction_date": at(r, 1),
        "disclosure_date": at(r, 5) if isinstance(at(r, 5), str) else None,
        "amount": {"range": text(at(r, 4)), "min": low, "max": high},
        "owner": text(at(r, 11)),
    }


def politician_holding(r):
    if not isinstance(r, list) or not isinstance(at(r, 9), str):
        return None
    return {
        "politician": {"name": text(at(r, 9)), "gender": text(at(r, 13)), "chamber": text(at(r, 14)),
                       "party": text(at(r, 15)),
                       "district": text(at(r, 16)) or None, "is_current": at(r, 10) if isinstance(at(r, 10), bool) else None},
        "asset_type": text(at(r, 3)),
        "owner": text(at(r, 1)),
        "disclosure_year": at(r, 5) if isinstance(at(r, 5), int) else None,
        "shares": {"min": to_int(at(r, 7)), "mid": to_int(at(r, 6)), "max": to_int(at(r, 8))},
    }
