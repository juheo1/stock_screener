# Stock Intelligence and Screener - Project Planner

Note: [S#] refers to source # in 99_sources.md file.

## Purpose
Build a local web application for stock intelligence and screening. Python runs the back end (data ingestion, metric computation, API). A web UI provides dashboards, filters, comparison tables, and exports.

The target UX is similar to the Felix & Friends "Stock Intelligence Suite" with:
- Smart Screener (threshold-based filtering)
- Zombie Detector (solvency risk list)
- Batch Compare (side-by-side metrics)
- Retirement projections
- Macro / liquidity monitor
- Metals intelligence

## Guiding concepts

### Fundamental metrics
Core metrics used in screening and scoring:
- Gross margin: profitability after direct costs [S1]
- ROIC: capital efficiency (how well invested capital is turned into operating profit) [S2]
- Free cash flow (FCF) margin: cash generation relative to revenue (FCF = operating cash flow - capex) [S3]
- Interest coverage ratio: ability to pay interest using earnings (often EBIT / interest expense) [S4]
- P/E ratio: valuation multiple based on price and earnings per share [S5]

### Zombie detection (solvency risk)
A "zombie company" is typically an indebted or uncompetitive company that can only cover interest on its debt (interest coverage <= 1) and lacks capacity to reduce principal, invest, or grow [S6].

Operational flag (configurable):
- Negative free cash flow (FCF < 0)
- Interest coverage < 1.0x
- Deteriorating gross margin trend (for example, 3-year slope < 0)

### User flows
Users should be able to:
1. View a dashboard with key market/macro indicators and summary counts.
2. Screen a large universe with threshold sliders/inputs.
3. Open a pre-built "Zombie Kill List" with reasons and export.
4. Compare up to 50 tickers side-by-side on a single screen.
5. Model retirement scenarios with year-by-year projections.
6. View metals prices and inventory, plus a personal stack tracker.
