"""The 25 Google Finance endpoints. Every path is served with and without the
`/google-finance` prefix, so code generated against the hosted API on
RapidAPI (paths like /details) runs unchanged against this server.

Params are validated by the marshmallow schemas in google_finance/schemas.py:
unknown or invalid params answer 400 with the reason."""
import json

from bottle import request, response, route

from google_finance import charts, fundamentals, holdings, insights, markets, news, peers, quotes
from google_finance import schemas as S
from schema_fields import load_query
from scraper_errors import BadRequest, NotFound


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Zürich" would arrive as "ZÃ¼rich")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def call(label, schema, fn):
    """Validate, run, map errors: bad params -> 400, missing entity -> 404,
    retries exhausted / blocked -> 500."""
    data, error = load_query(schema, query_dict())
    if error:
        return json_response(error, 400)
    try:
        result = fn(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"google finance rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:
        return json_response({"error": f"google finance {label} failed: {e}"}, 500)
    return json_response(result)


ENDPOINTS = [
    # (path, schema, function)
    ("/details", S.SymbolSchema, quotes.details),
    ("/search", S.SearchSchema, markets.search),
    ("/quote", S.SymbolSchema, quotes.quote),
    ("/quotes", S.QuotesSchema, quotes.quotes),
    ("/chart", S.ChartSchema, charts.chart),
    ("/financials", S.FinancialsSchema, fundamentals.financials),
    ("/earnings", S.SymbolSchema, fundamentals.earnings),
    ("/earnings-call", S.EarningsCallSchema, fundamentals.earnings_call),
    ("/analyst-ratings", S.SymbolSchema, fundamentals.analyst_ratings),
    ("/analysis", S.SymbolSchema, insights.analysis),
    ("/key-moments", S.SymbolSchema, insights.key_moments),
    ("/news", S.NewsSchema, news.news),
    ("/insider-transactions", S.CursorSchema, holdings.insider_transactions),
    ("/politician-trades", S.CursorSchema, holdings.politician_trades),
    ("/politician-holdings", S.CursorSchema, holdings.politician_holdings),
    ("/prediction-markets", S.SymbolSchema, insights.prediction_markets),
    ("/similar", S.SimilarSchema, peers.similar),
    ("/related", S.SymbolSchema, peers.related),
    ("/currency-convert", S.ConvertSchema, quotes.convert),
    ("/market-summary", S.MarketSchema, markets.market_summary),
    ("/market-movers", S.MoversSchema, markets.market_movers),
    ("/sectors", S.MarketSchema, markets.sectors),
    ("/trending", S.MarketSchema, markets.trending),
    ("/earnings-calendar", S.EarningsCalendarSchema, markets.earnings_calendar),
    ("/market-news", S.MarketNewsSchema, news.market_news),
]


def mount(path, schema, fn):
    """Serve a handler at /path and /google-finance/path."""
    def handler():
        return call(path.strip("/"), schema, fn)
    handler.__name__ = "google_finance_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/google-finance" + path, method="GET")(handler)


for _path, _schema, _fn in ENDPOINTS:
    mount(_path, _schema, _fn)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, _, _ in ENDPOINTS]})
