"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json.
"""
import json
import os

from google_finance.charts import chart
from google_finance.fundamentals import financials
from google_finance.quotes import details
from google_finance.symbols import parse_symbol

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a symbol, a bare ticker or any google.com/finance/quote link
    save("details_nvda.json", details(parse_symbol("NVDA:NASDAQ")))

    # 1D to MAX windows, or any date range with 1-minute to weekly candles
    save("chart_nvda_1y.json", chart(parse_symbol("NVDA:NASDAQ"), window="1Y"))

    # income statement, balance sheet and cash flow, every fiscal year
    save("financials_aapl_annual.json", financials(parse_symbol("AAPL:NASDAQ"), period="annual", limit=10))
