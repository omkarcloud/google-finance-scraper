"""Plumbing shared by the endpoint modules: one entity-scoped batch (the
ticker-row rpc rides along with every entity call, giving the canonical
identity and the not-found signal in the same POST), identity dicts and
list trimming."""
from google_finance import fetch, parsers, symbols

QUOTE_RPC = "gCvqoe"


def entity_batch(symbol, calls, *, language="en", country="US", label):
    """Resolve `symbol` and run [ticker row] + calls(descriptor) in ONE POST.

    calls: descriptor -> [(rpcid, args), …]
    Returns (ticker row dict, raw ticker row, [data | None per call])."""
    canonical, entity = symbols.resolve(symbol, language, country)
    extra = calls(entity)
    results = fetch.batch([(QUOTE_RPC, [[entity], 1])] + extra, language=language, country=country,
                          strict=False, label=label)
    head = fetch.ok(results[0])
    if isinstance(results[0], fetch.RpcError) and results[0].code in (3, 13):
        raise fetch.FinanceBadRequest(f"{label}: Google rejected the symbol {canonical}")
    if parsers.not_found(head):
        raise fetch.FinanceNotFound(f"{canonical}: not found on Google Finance")
    row = next(r for r in head[0][0] if parsers.is_ticker_row(r))
    return parsers.ticker_row(row), row, [fetch.ok(r) for r in results[1:]]


IDENTITY_KEYS = ("symbol", "ticker", "exchange", "name", "type", "link")


def identity(quote):
    return {k: quote.get(k) for k in IDENTITY_KEYS}


def with_identity(quote, **fields):
    out = identity(quote)
    out.update(fields)
    return out
