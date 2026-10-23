# 📈 Google Finance Scraper

Google Finance Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Google Finance data for free.

## ✨ What Can I Get?

- 💹 **Live quotes on 7 asset classes** — stocks, ETFs, mutual funds, indexes, futures, currencies & crypto, plus Kalshi & Polymarket odds
- 📊 **25+ years of financial statements** — income statement, balance sheet & cash flow, 90+ fields per quarter
- 🎙️ **Earnings calls, word for word** — 108 timed speaker segments in Apple's last call, plus audio, the 10-Q & AI highlights
- 🏛️ **30 analyst ratings on Apple alone** — plus insider Form 4 trades, Congress trades & holdings, and AI stock analysis

## 🎥 Example: A Full Google Finance Stock

```json
{
  "symbol": "NVDA:NASDAQ",
  "name": "NVIDIA Corp",
  "type": "stock",
  "link": "https://www.google.com/finance/quote/NVDA:NASDAQ",
  "industry": "Semiconductor",
  "quote": {
    "price": 225.07,
    "change": 0.49,
    "change_percent": 0.2182,
    "previous_close": 224.58,
    "currency": "USD",
    "extended_hours": { "session": "after_hours", "price": 225.0, "change": -0.07, "change_percent": -0.0322 }
  },
  "key_stats": {
    "day_high": 226.94,
    "day_low": 223.13,
    "year_high": 236.54,
    "year_low": 164.27,
    "volume": 89947712,
    "market_cap": 5424187000000,
    "pe_ratio": 28.45,
    "eps": 7.9107,
    "dividend_yield_percent": 0.4443,
    "beta": 2.2188
  },
  "profile": {
    "ceo": "Jensen Huang",
    "employees": 42000,
    "founded_date": "1993-04-05",
    "headquarters": { "city": "Santa Clara", "region": "California", "country": "United States" },
    "wikipedia_link": "https://en.wikipedia.org/wiki/Nvidia"
  },
  "news_sentiment": { "bullish_percent": 43.25, "neutral_percent": 51.28, "bearish_percent": 5.47, "articles_last_week": 319 }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Google Finance Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/google-finance-scraper
cd google-finance-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/details?symbol=NVDA:NASDAQ"
```

```json
{
  "symbol": "NVDA:NASDAQ",
  "name": "NVIDIA Corp",
  "industry": "Semiconductor",
  "quote": {
    "price": 225.07,
    "change": 0.49,
    "change_percent": 0.2182,
    "previous_close": 224.58,
    "currency": "USD"
  },
  "key_stats": {
    "year_high": 236.54,
    "year_low": 164.27,
    "market_cap": 5424187000000,
    "pe_ratio": 28.45,
    "eps": 7.9107,
    "beta": 2.2188
  },
  "profile": { "ceo": "Jensen Huang", "employees": 42000, "founded_date": "1993-04-05" }
}
```

All 25 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

25 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Stock Details | `/details` | Price, key stats, company profile and news sentiment in one call |
| Search | `/search` | Stocks, ETFs, funds, crypto, prediction markets and private companies |
| Quote / Batch Quotes | `/quote`, `/quotes` | Live prices with after-hours, up to 25 symbols per call |
| Price Chart | `/chart` | 1-minute to weekly candles, back to 1980, compare 4 symbols |
| Financial Statements | `/financials` | Income statement, balance sheet and cash flow, every quarter or year |
| Earnings | `/earnings` | EPS and revenue vs estimates, beat or miss, next report date |
| Earnings Call Transcript | `/earnings-call` | Timed transcript by speaker, audio, 10-Q and AI highlights |
| Analyst Ratings | `/analyst-ratings` | Consensus, price targets and every analyst's track record |
| AI Stock Analysis | `/analysis` | Why the stock moves, cited bullish and bearish arguments |
| Key Moments | `/key-moments` | Biggest price moves, each explained with its news sources |
| Stock News | `/news` | Latest headlines from the web and Google's news partners |
| Insider Transactions | `/insider-transactions` | Insider buys and sells with SEC Form 4 links |
| Politician Trades / Holdings | `/politician-trades`, `/politician-holdings` | Congress members' trades and share holdings |
| Prediction Markets | `/prediction-markets` | Kalshi and Polymarket odds linked to the stock |
| Similar / Related Stocks | `/similar`, `/related` | Peers with live quotes and latest quarterly results |
| Currency Converter | `/currency-convert` | Any amount between currencies and crypto, live rate |
| Market Summary | `/market-summary` | Headline indexes, currencies, crypto and futures by region |
| Market Movers | `/market-movers` | Top gainers, losers and most active, up to 50 each |
| Sector Performance | `/sectors` | Every equity sector index with the day's move |
| Trending | `/trending` | What's trending on Google Finance right now |
| Earnings Calendar | `/earnings-calendar` | Upcoming and this week's earnings with estimates |
| Market News | `/market-news` | AI market summary, top stories and latest financial news |


## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-google-finance-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-google-finance-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-google-finance-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/details",
    params={"symbol": "NVDA:NASDAQ"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Google Finance Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Google%20Finance%20Scraper%20API.)

[![Ask Us by Email about Google Finance Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Google%20Finance%20Scraper%20API&body=I%20need%20help%20using%20the%20Google%20Finance%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**IMDb Scraper**](https://github.com/omkarcloud/imdb-scraper) — movies, TV shows, ratings, cast & box office

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/google-finance-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/google-finance-scraper)
