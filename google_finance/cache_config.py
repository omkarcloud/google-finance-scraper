"""Cache TTL per /google-finance/* endpoint (cache.py, keyed on the
validated params — marshmallow fills the defaults, and a symbol's link
form and bare form share a row once parsed).

Prices move every second, so anything carrying a live quote caches for a
minute or two; statements, transcripts and filings barely move."""
from datetime import timedelta

# --- live prices ---------------------------------------------------------------------------
QUOTE_CACHE = timedelta(minutes=1)
QUOTES_CACHE = timedelta(minutes=1)
CONVERT_CACHE = timedelta(minutes=1)
DETAILS_CACHE = timedelta(minutes=2)
CHART_CACHE = timedelta(minutes=2)
MARKET_SUMMARY_CACHE = timedelta(minutes=2)
MARKET_MOVERS_CACHE = timedelta(minutes=2)
SECTORS_CACHE = timedelta(minutes=2)
SEARCH_CACHE = timedelta(minutes=10)
TRENDING_CACHE = timedelta(minutes=10)
SIMILAR_CACHE = timedelta(minutes=10)
RELATED_CACHE = timedelta(minutes=10)
PREDICTION_MARKETS_CACHE = timedelta(minutes=10)

# --- news / AI -------------------------------------------------------------------------------
NEWS_CACHE = timedelta(minutes=10)
MARKET_NEWS_CACHE = timedelta(minutes=10)
ANALYSIS_CACHE = timedelta(hours=3)
KEY_MOMENTS_CACHE = timedelta(hours=3)

# --- fundamentals ----------------------------------------------------------------------------
FINANCIALS_CACHE = timedelta(hours=12)
EARNINGS_CACHE = timedelta(hours=6)
EARNINGS_CALL_CACHE = timedelta(hours=12)
EARNINGS_CALENDAR_CACHE = timedelta(hours=1)
ANALYST_RATINGS_CACHE = timedelta(hours=6)
INSIDERS_CACHE = timedelta(hours=6)
POLITICIANS_CACHE = timedelta(hours=6)
