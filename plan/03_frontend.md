# Front End Plan

Choose one:
1. Dash (all-Python UI)
2. React SPA + FastAPI back end

Recommendation for a PC-local tool:
- Start with Dash for speed (one language, fewer moving parts).
- Migrate to React when you want a more complex UX.

## Pages and components

## 1. Intelligence Hub (Dashboard)
Components:
- Market cards (index proxy, VIX proxy)
- Summary cards (screened count, zombies count, quality count)
- Carry trade risk widget (v1: placeholder data; later: real model)
- Metals widget (spot prices, ratio)

## 2. Stock Screener
Controls:
- Sliders / numeric inputs for thresholds:
  - gross margin min
  - ROIC min
  - FCF margin min
  - interest coverage min
  - P/E max
- Quick presets buttons (High Quality, Value, Growth, Zombies, Clear)
- hide NA checkbox

Results:
- table grid with:
  - ticker, company, gross margin, ROIC, FCF margin, interest coverage, P/E
  - sortable columns
  - search
  - pagination
  - export CSV

Behavior:
- changes trigger an API call, update results without full refresh.

## 3. Zombie Kill List
Components:
- search input (ticker/name)
- filters (sector/industry)
- table with:
  - reasons (negative FCF, coverage < 1, margin deterioration)
  - severity score (optional)
- export CSV

## 4. Batch Compare
Components:
- ticker entry (chips list, max 50)
- analyze button
- results grid with:
  - pass/fail icons per metric threshold
  - overall score
  - heatmap coloring
- export Excel, export PDF

## 5. Retirement Planner
Inputs:
- current portfolio value or holdings
- contribution schedule
- ages and retirement target
- scenario assumptions

Outputs:
- chart with three scenario curves
- table with year-by-year values
- readiness score summary

## 6. Metals Intel
Components:
- spot price cards and small charts
- COMEX inventory chart (if available)
- gold/silver ratio
- personal stack tracker (transactions + current valuation)

## 7. Macro / Liquidity Monitor
Components:
- selectable timeframes (1Y, 2Y, 5Y, 10Y)
- charts for:
  - reverse repo
  - M2 money supply
  - government spending (if included)
