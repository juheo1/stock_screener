# Improvement Plan: Macro Intelligence & Sentiment Layer

## Overview

This document outlines proposed improvements to the stock screener, focused on three pillars:

1. **Fed Liquidity & Money Printing** — actual vs. implied printing, net liquidity tracking
2. **Global Macro Expansion** — broader economic indicators beyond the current 7 FRED series
3. **News, Sentiment & Geopolitical Risk** — real-time news feeds, event-driven signals, disaster tracking

---

## Part 1: Fed Liquidity & Money Printing

### 1.1 What "Actual Printing" Means

The Fed does not literally print money but expands its balance sheet by purchasing assets (Treasuries, MBS). This injects reserves into the banking system and is the closest proxy to "printing."

**FRED Series to Add:**

| FRED ID     | Name                             | Frequency | Notes                             |
|-------------|----------------------------------|-----------|-----------------------------------|
| WALCL       | Fed Total Assets (Balance Sheet) | Weekly    | Core "printing" signal            |
| WRESBAL     | Reserve Balances at Fed          | Weekly    | Money already in system           |
| WCURCIR     | Currency in Circulation          | Weekly    | Physical cash component           |
| M1SL        | M1 Money Supply                  | Monthly   | Narrow money (cash + demand deps) |
| WDTGAL      | Treasury General Account (TGA)   | Weekly    | Drains liquidity when it rises    |

### 1.2 Net Liquidity Formula (Implied Printing Signal)

The most-watched "implied printing" metric used by institutional traders:

```
Net Liquidity = Fed Balance Sheet (WALCL) - Reverse Repo (RRPONTSYD) - TGA (WDTGAL)
```

- **Rising Net Liquidity** → bullish for risk assets (money flowing into system)
- **Falling Net Liquidity** → bearish (money being absorbed back)
- **Overlay S&P 500 or NDX** to show correlation

This is the single most important new computed metric to add.

### 1.3 QE/QT Regime Detection

Derive the current regime from Fed balance sheet direction:

```
if WALCL 13-week trend > +$50B → QE_ACTIVE
elif WALCL 13-week trend < -$50B → QT_ACTIVE
else → NEUTRAL
```

Display as a regime badge on the Macro page and Dashboard.

---

## Part 2: Global Macro Expansion

### 2.1 Additional FRED Series

**Inflation & Prices:**

| FRED ID     | Name                          | Notes                              |
|-------------|-------------------------------|-------------------------------------|
| PCEPI       | PCE Price Index               | Fed's preferred inflation gauge     |
| PCEPILFE    | Core PCE (ex food/energy)     | Most watched by FOMC                |
| CPIMEDSL    | CPI Medical Care              | Healthcare cost proxy               |
| AHETOT      | Average Hourly Earnings       | Wage inflation signal               |

**Labor Market:**

| FRED ID     | Name                          | Notes                              |
|-------------|-------------------------------|-------------------------------------|
| UNRATE      | Unemployment Rate             | Lagging indicator                  |
| ICSA        | Initial Jobless Claims        | Leading indicator (weekly)          |
| PAYEMS      | Nonfarm Payrolls              | Monthly jobs added                 |
| CIVPART     | Labor Force Participation Rate| Structural employment health       |

**Credit & Spreads:**

| FRED ID     | Name                          | Notes                              |
|-------------|-------------------------------|-------------------------------------|
| BAMLH0A0HYM2| HY Credit Spread (OAS)        | Risk appetite / stress signal      |
| BAMLC0A0CM  | IG Credit Spread (OAS)        | Investment grade stress            |
| TEDRATE     | TED Spread                    | Interbank risk (Libor - T-bill)    |

**Global & Other:**

| FRED ID     | Name                          | Notes                              |
|-------------|-------------------------------|-------------------------------------|
| DTWEXBGS    | USD Broad Trade-Weighted Index| DXY-like, broader basket           |
| VIXCLS      | VIX Volatility Index          | Fear gauge                         |
| T10YIE      | 10Y Breakeven Inflation Rate  | Market-implied inflation expectation|
| T5YIFR      | 5Y5Y Forward Inflation Rate   | Long-run inflation expectations    |

### 2.2 Global Central Bank Tracking

Beyond the Fed, add:
- **ECB Total Assets** (ECB statistical data warehouse — not FRED, requires ECB API or manual series)
- **PBOC Balance Sheet** (People's Bank of China — via FRED series CHNASSETS or FRED proxies)
- **Global M2** = Sum of major central bank balance sheets as a derived metric

*Note: ECB/PBOC data may require web scraping or alternative data providers (Alpha Vantage, Quandl/Nasdaq Data Link).*

### 2.3 Economic Calendar

Track scheduled events:
- FOMC meeting dates and decisions
- CPI / PPI release dates
- NFP (nonfarm payrolls) release dates
- Earnings season markers

**Data source:** `pandas_market_calendars` + hardcoded FOMC dates, or scrape from `econoday.com` / `investing.com` calendar API.

---

## Part 3: News, Sentiment & Geopolitical Risk

### 3.1 News Data Sources

| Source              | API                      | Cost         | Best For                        |
|---------------------|--------------------------|--------------|----------------------------------|
| **NewsAPI.org**     | newsapi.org              | Free tier    | English financial/world news    |
| **Finnhub**         | finnhub.io               | Free tier    | Stock-specific news + sentiment |
| **Alpha Vantage**   | alphavantage.co          | Free tier    | News sentiment with tickers     |
| **GDELT Project**   | gdeltproject.org         | Free (public)| Geopolitical events, global news|
| **USGS Earthquake** | earthquake.usgs.gov/fdsnws| Free (public)| Real-time earthquake data       |
| **ReliefWeb**       | reliefweb.int/api        | Free (public)| Humanitarian/disaster events    |
| **RSS Feeds**       | FT, Reuters, Bloomberg   | Free RSS     | Major outlets via feedparser    |

### 3.2 Sentiment Indicators

**Market Sentiment:**

| Indicator              | Source                          | Method                              |
|------------------------|---------------------------------|--------------------------------------|
| CNN Fear & Greed Index | Scraped from money.cnn.com      | HTTP scrape or inferred from components|
| AAII Investor Sentiment| aaii.com (weekly survey)        | Scrape or manual CSV import         |
| Put/Call Ratio         | CBOE via yfinance (^PCCE, ^PCCI)| Pull from Yahoo Finance             |
| VIX / VIX9D            | yfinance (^VIX, ^VIX9D)         | Already available                   |
| Short Interest         | Finviz, FINRA, or iborrowdesk   | Scrape or API                       |

**NLP Sentiment Scoring:**

Use a lightweight model to score news headlines:
- **VADER** (rule-based, no GPU needed, `vaderSentiment` package) — fast, good for financial text
- **FinBERT** (transformer, Hugging Face) — higher accuracy, heavier
- **Finnhub's built-in sentiment score** — pre-computed, easiest to implement

### 3.3 Geopolitical Risk Signals

**GDELT Integration:**
- GDELT Global Knowledge Graph API can return real-time events tagged by country, actor, and event type
- Goldstein Scale score (-10 to +10) measures conflict/cooperation intensity
- Can filter for: military action, sanctions, natural disasters, political unrest

**USGS Earthquake Feed:**
- `https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&minmagnitude=5.5&limit=50`
- Real-time feed of M5.5+ earthquakes globally
- Parse: magnitude, location, depth, time
- Flag if event is in a major economic zone (Japan, SE Asia, Turkey, etc.)

**Other Event Types to Track:**
- Sanctions (OFAC list changes) — via Treasury RSS or news keyword filter
- Shipping disruption (Strait of Hormuz, Suez Canal) — keyword filter from GDELT
- Energy supply disruption — keyword filter + oil price spike correlation

---

## Part 4: Page-Level Implementation Plan

### 4.1 Revised `macro.py` Page → "Macro & Liquidity Monitor" (Expanded)

**Current state:** 7 FRED series in static charts.

**Proposed revisions:**
- Add **Net Liquidity gauge** as top KPI card with QE/QT regime badge
- Add Fed Balance Sheet chart overlaid with S&P 500 (dual-axis)
- Group series into tabs: `Liquidity`, `Inflation`, `Labor`, `Credit`, `Global`
- Add "Implied Printing Rate" 4-week rolling change on Fed assets
- Add 10Y Breakeven vs CPI overlay (real vs expected inflation)
- Add HY/IG credit spread chart with recession shading
- Add VIX chart with historical percentile annotation

### 4.2 New Page: `liquidity.py` — Fed Liquidity Dashboard

If the expanded macro page becomes too crowded, extract liquidity into its own page.

**Sections:**
1. **Net Liquidity Tracker** — WALCL - RRPONTSYD - TGA with S&P overlay, QE/QT regime badge
2. **Money Supply Growth** — M1, M2 YoY% charts
3. **Fed Balance Sheet Composition** — Treasuries vs MBS as stacked bar
4. **Reserve Balances** — Bank reserves at the Fed (excess vs required)
5. **TGA Balance** — Treasury spending drawdown as bullish signal
6. **Implied Printing Signal** — 4-week, 13-week, 52-week Fed balance sheet changes

**API changes needed:** New FRED series ingestion, new `/liquidity` endpoint.

### 4.3 New Page: `sentiment.py` — News & Sentiment Hub

**Sections:**
1. **Sentiment Gauges** (top bar)
   - Fear & Greed score (0-100 with color gradient)
   - Put/Call Ratio
   - VIX percentile
   - AAII Bull-Bear spread

2. **News Feed** (main panel)
   - Filterable by: All / Financial / Geopolitical / Macro / Disasters
   - Each card shows: headline, source, time, NLP sentiment score (Bullish/Neutral/Bearish)
   - Keyword search
   - Auto-refresh every 15 minutes

3. **Geopolitical Risk Panel**
   - GDELT Goldstein Score trend (world avg)
   - Top 5 active conflict/tension zones
   - Recent significant events table

4. **Natural Disaster Feed**
   - M5.5+ earthquakes last 7 days (from USGS)
   - Economic impact estimate by region
   - Other disaster types from ReliefWeb

5. **Ticker-Level News** (bottom)
   - Enter a ticker → fetch Finnhub/Alpha Vantage news for that ticker
   - Sentiment breakdown pie chart per ticker

**API changes needed:** New `/sentiment` and `/news` endpoints. New ingestion modules for each data source.

### 4.4 New Page: `calendar.py` — Economic Calendar

**Sections:**
1. **This Week** — highlighted current week events
2. **Month View** — calendar grid with event markers
3. **Event Types:**
   - FOMC meetings & minutes (hardcoded schedule)
   - Major economic releases (CPI, PPI, NFP, PCE, ISM)
   - Earnings season markers
   - Options expiry (monthly + quarterly)
4. **Countdown timers** to next FOMC meeting and next CPI release
5. **Historical Impact** — when clicked, show what market did after last N occurrences of same event

### 4.5 Revised `dashboard.py` — Add Macro Regime Awareness

**Proposed additions:**
- **Macro Regime Banner** at top: shows QE/QT status, current Fed rate, next FOMC date
- **Sentiment Ticker Bar** — scrolling strip with VIX, Put/Call, Fear/Greed score
- **News Alert Badge** — count of high-impact news items in last 24h with severity color
- **Net Liquidity Delta** KPI card alongside existing market KPIs

### 4.6 Revised `screener.py` / `screener_rok.py` — Macro-Conditional Filters

Add a **"Macro Regime Filter"** toggle:
- In QT/tightening regime → auto-apply: higher quality score threshold, higher FCF margin floor
- In QE/easing regime → relax quality thresholds, allow more growth-oriented filters
- User can override, but regime-aware presets become new preset options: `QE Regime`, `QT Regime`, `Recession Defense`

---

## Part 5: Backend / Ingestion Architecture

### 5.1 New Ingestion Modules

| Module                       | File                              | Frequency  |
|------------------------------|-----------------------------------|------------|
| Fed Liquidity (expanded FRED) | `src/ingestion/liquidity.py`      | Weekly     |
| News API ingest               | `src/ingestion/news.py`           | Hourly     |
| Sentiment indicators          | `src/ingestion/sentiment.py`      | Daily      |
| GDELT geopolitical            | `src/ingestion/geopolitical.py`   | Every 6h   |
| USGS Earthquake feed          | `src/ingestion/disasters.py`      | Every 1h   |
| Economic calendar             | `src/ingestion/calendar_events.py`| Weekly     |

### 5.2 New Database Tables

```sql
-- News articles with NLP sentiment
news_articles (id, headline, source, url, published_at, category, sentiment_score, sentiment_label, related_tickers)

-- Geopolitical events from GDELT
geopolitical_events (id, event_date, actor1, actor2, goldstein_scale, event_type, country_code, lat, lon, source_url)

-- Earthquake events
earthquake_events (id, event_time, magnitude, depth_km, location, lat, lon, economic_zone_flag)

-- Composite sentiment scores (daily snapshots)
sentiment_daily (id, date, fear_greed_score, put_call_ratio, vix_value, vix_percentile, aaii_bull_pct, aaii_bear_pct)

-- Economic calendar events
economic_calendar (id, event_date, event_name, event_type, importance, actual, forecast, previous)
```

### 5.3 New API Endpoints

```
GET /liquidity              → Net liquidity, QE/QT regime, Fed asset composition
GET /liquidity/{series_id}  → Individual liquidity series historical data
GET /news                   → Latest news articles (filterable by category, sentiment)
GET /news/{ticker}          → Ticker-specific news
GET /sentiment/latest       → Latest composite sentiment snapshot
GET /sentiment/history      → Sentiment time-series (Fear/Greed, Put/Call, VIX %-ile)
GET /geopolitical/events    → Recent GDELT events (filterable by country, type)
GET /disasters/earthquakes  → Recent M5.5+ earthquakes
GET /calendar               → Upcoming economic events (next 30 days)
GET /calendar/history/{event_type} → Historical market reaction to past events
```

---

## Part 6: Priority & Sequencing

### Phase A — High Value, Low Complexity (Start Here)

1. **Add WALCL + TGA to FRED ingestion** → compute Net Liquidity → add to Macro page
2. **Add VIX, Put/Call (via yfinance ^VIX, ^PCCE)** → sentiment KPI card on Dashboard
3. **Add USGS earthquake feed** → simple table on a new `disasters` section or Sentiment page
4. **Expand FRED series** (Core PCE, jobless claims, HY spread) → group into tabs on Macro page

### Phase B — Medium Complexity

5. **News ingest via NewsAPI or Finnhub** → store in DB → build News Feed panel
6. **VADER sentiment scoring** on ingested headlines
7. **New `sentiment.py` page** with news feed + gauge cards
8. **Fear & Greed scraper** (or infer from VIX + Put/Call + breadth)
9. **Economic Calendar page** with FOMC countdown

### Phase C — Higher Complexity

10. **GDELT integration** (geopolitical events + Goldstein score trend)
11. **Macro-conditional screener presets** (QE/QT regime-aware filters)
12. **Fed Balance Sheet composition chart** (requires parsing H.4.1 release or multiple FRED series)
13. **Ticker-level news sentiment** with per-stock sentiment breakdown

---

## Part 7: Data Provider Summary

| Provider         | Data                          | Key Limitation                        | API Key Required |
|-----------------|-------------------------------|---------------------------------------|-----------------|
| FRED (existing) | Macro series                  | Weekly lag on balance sheet data      | Yes (existing)  |
| yfinance        | ^VIX, ^PCCE, ^PCCI            | No official API, scrape               | No              |
| NewsAPI.org     | General news                  | 100 req/day free, 1-month history     | Yes (free)      |
| Finnhub         | Stock news + sentiment scores | 60 req/min free                       | Yes (free)      |
| Alpha Vantage   | News with ticker tags         | 25 req/day free                       | Yes (free)      |
| GDELT           | Geopolitical events           | Complex schema, 15-min update delay   | No              |
| USGS            | Earthquake data               | Earthquake data only                  | No              |
| ReliefWeb       | Humanitarian disasters        | Slower update cycle (days)            | No              |
| VADER / FinBERT | NLP sentiment scoring         | Local computation, FinBERT needs GPU  | No (local)      |

---

## Part 8: Environment Variables to Add

```
# .env additions
NEWSAPI_KEY=your_newsapi_key
FINNHUB_API_KEY=your_finnhub_key
ALPHAVANTAGE_API_KEY=your_av_key

# Feature flags (optional — allow partial rollout)
ENABLE_NEWS_FEED=true
ENABLE_GDELT=false          # Off by default (high data volume)
ENABLE_SENTIMENT=true
ENABLE_EARTHQUAKE=true
```

---

## Summary of New Pages

| Page              | Nav Label             | Priority | Dependencies                        |
|-------------------|-----------------------|----------|--------------------------------------|
| `liquidity.py`    | Fed Liquidity         | High     | WALCL, TGA from FRED                |
| `sentiment.py`    | News & Sentiment      | High     | NewsAPI, Finnhub, USGS, VADER       |
| `calendar.py`     | Economic Calendar     | Medium   | FOMC dates, FRED release calendar   |

## Summary of Revised Pages

| Page             | Key Changes                                                       |
|------------------|-------------------------------------------------------------------|
| `macro.py`       | Tabbed layout, Net Liquidity KPI, breakeven inflation, VIX, HY spread |
| `dashboard.py`   | Macro regime banner, sentiment ticker, net liquidity KPI card    |
| `screener.py`    | QE/QT-aware preset filters                                        |
| `screener_rok.py`| Same macro-aware presets for Korean market                       |
