"""Price charts (c2u4wc), exactly what the quote page's chart requests.

  window mode   [[entities], window code]                     1D … MAX presets
  range mode    [[entities], null, [[y,m,d], [y,m,d], interval code]]
  candles       8th arg 1 -> OHLC candles instead of line points

Measured 2026-09-26 on AAPL: window 1D = 391 one-minute points + the
after-hours session, 5D = 30-minute, 1M / 6M / YTD / 1Y daily, 5Y / MAX
weekly (MAX reaches 1980). In range mode the daily and weekly intervals
reach the listing's first trade (1980-12-12 for AAPL), 30-minute bars go
back ~20 months and 1-minute bars ~3 weeks; line mode returns only the
last session for the 15-minute and 1-hour intervals, so range mode always
asks for candles. Several entities in one call = the page's Compare.
"""
from datetime import date, timedelta

from google_finance import fetch, parsers, symbols
from google_finance.common import entity_batch, identity

WINDOWS = {"1D": 1, "5D": 2, "1M": 3, "6M": 4, "YTD": 5, "1Y": 6, "5Y": 7, "MAX": 8}
INTERVALS = {"1min": 1, "5min": 2, "15min": 3, "30min": 4, "1hour": 5, "1day": 6, "1week": 7}
MAX_COMPARE = 4


def auto_interval(start, end):
    span = (end - start).days
    if span <= 7:
        return "5min"
    if span <= 31:
        return "30min"
    if span <= 5 * 366:
        return "1day"
    return "1week"


def _series_args(entities, window, start_date, end_date, interval, candles):
    if start_date or end_date:
        end = end_date or date.today()
        start = start_date or (end - timedelta(days=30))
        if start > end:
            raise ValueError("start_date must be on or before end_date")
        interval = interval or auto_interval(start, end)
        rng = [[start.year, start.month, start.day], [end.year, end.month, end.day], INTERVALS[interval]]
        return [entities, None, rng, None, None, None, None, 1], interval, True
    return [entities, WINDOWS[window], None, None, None, None, None, 1 if candles else 0], None, candles


INTERVAL_NAMES = {60: "1min", 300: "5min", 900: "15min", 1800: "30min", 3600: "1hour", 86400: "1day",
                  604800: "1week"}


def _shape(series, identity_fields=None):
    """One series -> {…identity, format, interval, count, prices}. Currency /
    crypto pairs only come as daily line points, whatever was asked."""
    fmt = "candles" if series["candles"] else "line"
    prices = series["candles"] if fmt == "candles" else series["points"]
    out = dict(identity_fields or {"symbol": series["symbol"], "name": series["name"], "type": series["type"],
                                   "link": parsers.quote_link(series["symbol"])})
    out.update({"currency": series["currency"], "format": fmt,
                "interval": INTERVAL_NAMES.get(series["interval_seconds"]),
                "interval_seconds": series["interval_seconds"], "count": len(prices), "prices": prices})
    return out


def chart(symbol, window="1D", start_date=None, end_date=None, interval=None, candles=False, compare=None,
          language="en"):
    """Price history for one symbol (+ up to MAX_COMPARE compared symbols)."""
    others = symbols.resolve_many(compare or [], language) if compare else []

    def calls(entity):
        args, _interval, _candles = _series_args([entity] + [e for _, e in others], window, start_date,
                                                 end_date, interval, candles)
        return [("c2u4wc", args)]

    q, _row, (data,) = entity_batch(symbol, calls, language=language, label="chart")
    series = parsers.chart(data)
    main = next((s for s in series if s["symbol"] == q["symbol"] or (s["google_mid"] and s["google_mid"] == q.get("google_mid"))),
                series[0] if series else None)
    shaped = _shape(main, identity(q)) if main else dict(identity(q), currency=q.get("currency"), format=None,
                                                          interval=None, interval_seconds=None, count=0, prices=[])
    out = {k: shaped[k] for k in ("symbol", "ticker", "exchange", "name", "type", "link")}
    out.update({
        "window": None if (start_date or end_date) else window,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "price": q.get("price"),
        "previous_close": q.get("previous_close"),
    })
    out.update({k: shaped[k] for k in ("currency", "format", "interval", "interval_seconds", "count", "prices")})
    out["comparisons"] = [_shape(s) for s in series if s is not main]
    return out
