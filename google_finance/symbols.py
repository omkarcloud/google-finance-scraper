"""The ONE `symbol` input (tripadvisor QueryOrIdField convention): every
/google-finance/* route takes a single `symbol` that may be

  * a Google Finance symbol    AAPL:NASDAQ, .INX:INDEXSP, VFIAX:MUTF,
                               ESW00:CME_EMINIS, RELIANCE:NSE,
                               KXRECSSNBER-26:KALSHI (prediction market)
  * a currency / crypto pair   USD-INR, BTC-USD, eur/usd
  * a Google Finance link      https://www.google.com/finance/quote/AAPL:NASDAQ?window=1M
                               (the /finance/beta/quote/ form too)
  * a knowledge-graph id       /m/07zmbvf
  * a bare ticker              AAPL, TSLA — resolved through Google
                               Finance's own search (the page no longer
                               redirects bare tickers; /quote/AAPL is an
                               empty shell)

parse_symbol() is the offline validation used by the marshmallow field;
resolve() turns its output into (canonical symbol, rpc entity descriptor),
running one search for bare tickers.
"""
import re
import threading
import time
from urllib.parse import unquote, urlparse

from google_finance import fetch, parsers

_LISTING_RE = re.compile(r"^([A-Za-z0-9.\-^_=&/]{1,80}):([A-Za-z0-9_\-]{1,30})$")
_PAIR_RE = re.compile(r"^([A-Za-z0-9]{2,10})\s*[-/ ]\s*([A-Za-z0-9]{2,10})$")
_MID_RE = re.compile(r"^/[mg]/[A-Za-z0-9_]+$")
_BARE_RE = re.compile(r"^[A-Za-z0-9.\-^_=&]{1,24}$")
_CASE_SENSITIVE = {"POLYMARKET", "CRUNCHBASE"}   # Polymarket slugs and Crunchbase uuids are lowercase

BARE_PREFIX = "?"                  # parse_symbol output for a ticker that still needs a search


def parse_symbol(value):
    """Offline normalisation -> 'AAPL:NASDAQ' | 'USD-INR' | '/m/…' | '?AAPL'
    (a bare ticker to look up). Raises ValueError with a user-facing message."""
    value = (value or "").strip()
    if not value:
        raise ValueError("symbol must not be empty")
    if value.startswith(("http://", "https://", "//")) or "google." in value.split("/")[0]:
        url = value if "://" in value else "https://" + value.lstrip("/")
        host = (urlparse(url).hostname or "").lower()
        if "google." not in host:
            raise ValueError("symbol link must be a google.com/finance/quote/… link")
        m = re.search(r"/finance/(?:beta/)?quote/([^/?#]+)", urlparse(url).path)
        if not m:
            raise ValueError("symbol link must look like https://www.google.com/finance/quote/AAPL:NASDAQ")
        value = unquote(m.group(1))
    if _MID_RE.match(value):
        return value
    m = _LISTING_RE.match(value)
    if m:
        ticker, exchange = m.group(1), m.group(2).upper()
        return f"{ticker if exchange in _CASE_SENSITIVE else ticker.upper()}:{exchange}"
    m = _PAIR_RE.match(value)
    if m and not value.isalnum():
        return f"{m.group(1).upper()}-{m.group(2).upper()}"
    if _BARE_RE.match(value):
        return BARE_PREFIX + value.upper()
    raise ValueError("symbol must be TICKER:EXCHANGE (AAPL:NASDAQ), a pair (USD-INR, BTC-USD), "
                     "a ticker (AAPL) or a google.com/finance/quote link")


def descriptor(symbol):
    """Canonical symbol -> the rpc entity descriptor."""
    if symbol.startswith("/"):
        return [symbol]
    if ":" in symbol:
        ticker, exchange = symbol.rsplit(":", 1)
        return [None, [ticker, exchange]]
    base, quote = symbol.split("-", 1)
    return [None, None, [base, quote]]


# ---- bare-ticker resolution -------------------------------------------------------------------

_cache = {}
_lock = threading.Lock()
_TTL = 6 * 3600


def search_rows(query, language="en", country="US"):
    """Google Finance's search box (XB3kn; RelbPe / mKsvE are the older ids
    for the same backend) -> raw result rows in display order, deduped."""
    calls = [("XB3kn", [query, None, 1]), ("mKsvE", [query])]
    results = fetch.batch(calls, language=language, country=country, strict=False, label="search")
    data = next((fetch.ok(r) for r in results if fetch.ok(r)), None)
    rows, seen = [], set()
    for section in (data or []):
        if not isinstance(section, list):
            continue
        for row in section:
            quote = parsers.at(row, 3) if isinstance(row, list) else None
            key = parsers.symbol_of(quote) if isinstance(quote, list) else None
            key = key or (parsers.at(row, 7) if isinstance(row, list) else None)
            if isinstance(row, list) and key and key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


def _lookup(ticker, language, country):
    key = (ticker, country)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[1] > time.time():
            return hit[0]
    rows = search_rows(ticker, language=language, country=country)
    listed = [parsers.at(r, 3) for r in rows if isinstance(parsers.at(r, 3), list)]
    exact = [q for q in listed if (parsers.at(q, 1, 0) or "").upper() == ticker
             or (parsers.symbol_of(q) or "").upper() == ticker]
    best = (exact or listed or [None])[0]
    symbol = parsers.symbol_of(best) if best else None
    if not symbol:
        raise fetch.FinanceNotFound(f"no Google Finance listing matches '{ticker}' (try TICKER:EXCHANGE, e.g. AAPL:NASDAQ)")
    with _lock:
        _cache[key] = (symbol, time.time() + _TTL)
    return symbol


def resolve(symbol, language="en", country="US"):
    """parse_symbol() output -> (canonical symbol, entity descriptor)."""
    if symbol.startswith(BARE_PREFIX):
        symbol = _lookup(symbol[len(BARE_PREFIX):], language, country)
    return symbol, descriptor(symbol)


def resolve_many(symbols, language="en", country="US"):
    """Resolve a list (bare tickers searched concurrently)."""
    from concurrent.futures import ThreadPoolExecutor
    if not any(s.startswith(BARE_PREFIX) for s in symbols):
        return [resolve(s, language, country) for s in symbols]
    with ThreadPoolExecutor(max_workers=min(6, len(symbols))) as pool:
        return list(pool.map(lambda s: resolve(s, language, country), symbols))
