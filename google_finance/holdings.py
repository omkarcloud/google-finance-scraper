"""The quote page's Holdings tab (K5Y6Xb): corporate insider transactions
(SEC Form 4, TipRanks) and US politicians' trades and holdings of the
stock. One rpc answers all three lists, each with its own opaque cursor:

    K5Y6Xb [E, null, null, null, null, holdings cursor, trades cursor,
            insiders cursor]
    -> [0 holdings, 1 trades, 2, 3, 4 insider transactions, 5,
        6 holdings cursor, 7 trades cursor, 8 insiders cursor]

(Cursor slots found by replaying each returned cursor in every argument
position, 2026-09-26: slot 5 pages holdings, 6 trades, 7 insiders.)
"""
import base64
import binascii

from google_finance import fetch, parsers
from google_finance.common import entity_batch, identity
from google_finance.shared import at

RPC = "K5Y6Xb"
LISTS = {  # name -> (data slot, cursor arg slot, next-cursor slot, parser)
    "holdings": (0, 5, 6, parsers.politician_holding),
    "trades": (1, 6, 7, parsers.politician_trade),
    "insiders": (4, 7, 8, parsers.insider_transaction),
}
INVALID_CURSOR = "invalid cursor: pass the next_cursor value from the previous page unchanged"


def _check_cursor(cursor):
    if cursor is None:
        return
    try:
        base64.b64decode(cursor + "=" * (-len(cursor) % 4), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(INVALID_CURSOR)


def _page(symbol, which, cursor, language):
    slot, arg_slot, next_slot, parse = LISTS[which]
    _check_cursor(cursor)

    def calls(entity):
        args = [entity, None, None, None, None, None, None, None]
        args[arg_slot] = cursor
        return [(RPC, args)]

    try:
        q, _row, (data,) = entity_batch(symbol, calls, language=language, label=f"politicians {which}")
    except fetch.FinanceBadRequest:
        raise ValueError(INVALID_CURSOR) if cursor else fetch.FinanceBadRequest(f"{which}: Google rejected the request")
    items = [x for x in (parse(r) for r in (at(data, slot) or [])) if x]
    next_cursor = at(data, next_slot) if isinstance(at(data, next_slot), str) else None
    return q, items, next_cursor


def insider_transactions(symbol, cursor=None, language="en"):
    """Company insiders' buys and sells (Form 4), newest first."""
    q, items, next_cursor = _page(symbol, "insiders", cursor, language)
    out = identity(q)
    out.update({"count": len(items), "next_cursor": next_cursor, "has_more": bool(next_cursor),
                "transactions": items})
    return out


def politician_trades(symbol, cursor=None, language="en"):
    """US Congress members' (and executive officials') disclosed trades of
    the stock, newest first."""
    q, items, next_cursor = _page(symbol, "trades", cursor, language)
    out = identity(q)
    out.update({"count": len(items), "next_cursor": next_cursor, "has_more": bool(next_cursor), "trades": items})
    return out


def politician_holdings(symbol, cursor=None, language="en"):
    """US politicians' disclosed holdings of the stock (share ranges)."""
    q, items, next_cursor = _page(symbol, "holdings", cursor, language)
    out = identity(q)
    out.update({"count": len(items), "next_cursor": next_cursor, "has_more": bool(next_cursor), "holdings": items})
    return out
