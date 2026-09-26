"""Generic value helpers for Google's positional arrays. A copy of the five
google_search/shared.py helpers this package uses, kept local so
google_finance is self-contained (it ships standalone as the open-source
Google Finance Scraper)."""
import html as htmllib
import re
from datetime import datetime, timezone

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def at(seq, *path, default=None):
    """Safe nested index into Google's positional arrays: at(d, 0, 3, 1)."""
    cur = seq
    for key in path:
        try:
            cur = cur[key]
        except (IndexError, KeyError, TypeError):
            return default
        if cur is None:
            return default
    return cur


def clean_text(value):
    """Strip tags, unescape entities and collapse whitespace; '' -> None."""
    if value is None:
        return None
    text = _TAG_RE.sub("", str(value))
    text = htmllib.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text or None


def to_int(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d\-]", "", str(value))
    try:
        return int(digits) if digits not in ("", "-") else None
    except ValueError:
        return None


def iso_from_ts(ts):
    """Unix seconds -> ISO-8601 UTC string."""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def iso_date(parts):
    """Google's [year, month, day, ...] date array -> 'YYYY-MM-DD'."""
    if not isinstance(parts, list) or len(parts) < 3:
        return None
    try:
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    except (TypeError, ValueError):
        return None
