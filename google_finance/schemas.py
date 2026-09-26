"""Marshmallow request schemas for every /google-finance/* route. Each
schema's load() output is the kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a
sibling `url` / `id` pair): `symbol` takes a Google Finance symbol
(AAPL:NASDAQ), a currency / crypto pair (USD-INR), a bare ticker (AAPL —
looked up through Google Finance search), a knowledge-graph id (/m/07zmbvf)
OR a google.com/finance/quote link; see google_finance/symbols.py.
"""
from datetime import date

from marshmallow import ValidationError, post_load, validate, validates_schema

from google_finance import charts, fundamentals, markets, news, peers, quotes, symbols
from schema_fields import (BaseSchema, ChoiceField, CommaListField, CountryCodeField, DateField, Flag,
                           LanguageCodeField, LimitField, NonNegativeNumber, PositiveInt, QueryField, RefField,
                           StrippedString)


# ---- fields ---------------------------------------------------------------------------------

class SymbolField(RefField):
    resolver = staticmethod(symbols.parse_symbol)


class SymbolsField(CommaListField):
    """Comma-separated symbols (any `symbol` form except links with commas)."""

    def __init__(self, max_items, required=False, **kwargs):
        from marshmallow import missing
        super().__init__(upper=False, max_items=max_items, **kwargs)
        if required:   # CommaListField defaults to optional (load_default=None)
            self.required = True
            self.load_default = missing

    def _deserialize(self, value, attr, data, **kwargs):
        items = super()._deserialize(value, attr, data, **kwargs) or []
        out = []
        for item in items:
            try:
                parsed = symbols.parse_symbol(item)
            except ValueError as e:
                raise ValidationError(f"'{item}': {e}")
            if parsed not in out:
                out.append(parsed)
        return out


class CountryField(CountryCodeField):
    """ISO country picking the market (default US; "UK" accepted for GB)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", "US")
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        if isinstance(value, str) and value.strip().upper() == "UK":
            value = "GB"
        return super()._deserialize(value, attr, data, **kwargs)


class LanguageField(LanguageCodeField):
    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", "en")
        super().__init__(**kwargs)


class CurrencyCodeField(StrippedString):
    """A currency or cryptocurrency code: USD, EUR, INR, BTC, ETH, USDT…"""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", True)
        kwargs.setdefault("validate", validate.Regexp(r"^[A-Za-z0-9]{2,10}$",
                                                      error="Must be a currency code like USD, EUR or BTC."))
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        return value.upper() if value else value


class CursorField(StrippedString):
    """Opaque next_cursor from the previous page (absent = first page)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.Length(max=2000))
        super().__init__(**kwargs)


# ---- symbol routes ------------------------------------------------------------------------------

class SymbolSchema(BaseSchema):
    symbol = SymbolField()
    language = LanguageField()


class QuotesSchema(BaseSchema):
    symbols_list = SymbolsField(max_items=quotes.MAX_QUOTES, required=True, data_key="symbols")
    language = LanguageField()

    @post_load
    def need_one(self, data, **kwargs):
        if not data.get("symbols_list"):
            raise ValidationError({"symbols": ["List at least one symbol."]})
        return data


class ChartSchema(BaseSchema):
    symbol = SymbolField()
    window = ChoiceField(list(charts.WINDOWS), load_default="1D")
    start_date = DateField(bound="past")
    end_date = DateField(bound="past")
    interval = ChoiceField(list(charts.INTERVALS))
    candles = Flag(load_default=False)
    compare = SymbolsField(max_items=charts.MAX_COMPARE)
    language = LanguageField()

    @post_load
    def to_dates(self, data, **kwargs):
        data["window"] = data["window"].upper()
        for key in ("start_date", "end_date"):
            if data.get(key):
                data[key] = date.fromisoformat(data[key])
        if data.get("interval") and not (data.get("start_date") or data.get("end_date")):
            raise ValidationError({"interval": ["interval applies to a start_date / end_date range; "
                                                "a window has its own fixed interval."]})
        if data.get("start_date") and data.get("end_date") and data["start_date"] > data["end_date"]:
            raise ValidationError({"start_date": ["Must be on or before end_date."]})
        return data


class FinancialsSchema(BaseSchema):
    symbol = SymbolField()
    period = ChoiceField(list(fundamentals.PERIODS), load_default="quarterly")
    limit = LimitField(default=8, max_size=120)
    language = LanguageField()


class EarningsCallSchema(BaseSchema):
    symbol = SymbolField()
    fiscal_year = PositiveInt(max_value=2100)
    fiscal_quarter = PositiveInt(max_value=4)
    language = LanguageField()

    @validates_schema
    def both_or_none(self, data, **kwargs):
        if (data.get("fiscal_year") is None) != (data.get("fiscal_quarter") is None):
            raise ValidationError("Pass fiscal_year and fiscal_quarter together (or neither for the latest call).")


class CursorSchema(BaseSchema):
    symbol = SymbolField()
    cursor = CursorField()
    language = LanguageField()


class NewsSchema(BaseSchema):
    symbol = SymbolField()
    limit = LimitField(default=20, max_size=news.MAX_NEWS)
    language = LanguageField()


class SimilarSchema(BaseSchema):
    symbol = SymbolField()
    limit = LimitField(default=10, max_size=peers.MAX_SIMILAR)
    language = LanguageField()


class ConvertSchema(BaseSchema):
    from_currency = CurrencyCodeField()
    to_currency = CurrencyCodeField()
    amount = NonNegativeNumber(load_default=1.0)
    language = LanguageField()


# ---- market routes ------------------------------------------------------------------------------

class MarketSchema(BaseSchema):
    country = CountryField()
    language = LanguageField()


class SearchSchema(MarketSchema):
    query = QueryField(max_length=100)
    limit = LimitField(default=20, max_size=50)


class MoversSchema(MarketSchema):
    type = ChoiceField(["all"] + list(markets.MOVER_TYPES), load_default="all")
    limit = LimitField(default=20, max_size=markets.MAX_MOVERS)


class EarningsCalendarSchema(MarketSchema):
    period = ChoiceField(list(markets.CALENDAR_PERIODS), load_default="upcoming")


class MarketNewsSchema(MarketSchema):
    limit = LimitField(default=20, max_size=30)
