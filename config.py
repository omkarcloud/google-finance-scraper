"""Configuration for the Google Finance Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                  port the API listens on (default 8000)
    GOOGLE_FINANCE_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                          (default: none — direct). Google Finance answered
                          300+ direct calls in a row without a single rate
                          limit, so you very likely don't need this. Set it
                          only if you start seeing HTTP 429 at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy: a blocked or failed request is retried this many times.
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

GOOGLE_FINANCE_PROXY = os.environ.get("GOOGLE_FINANCE_PROXY") or None

# Names the google_finance/ package reads.
GOOGLE_FINANCE_MAX_ATTEMPTS = MAX_RETRIES
GOOGLE_FINANCE_DIRECT_COOLDOWN = 900
# The browser fallback needs Chrome + patchright; this kit is plain HTTP.
GOOGLE_FINANCE_BROWSER_FALLBACK = False
GOOGLE_FINANCE_BROWSER_IDLE_SECONDS = 300


def google_finance_proxy():
    return os.environ.get("GOOGLE_FINANCE_PROXY") or None


def google_finance_fallback_proxy():
    return None
