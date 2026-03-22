# 07 — UI Improvements Plan

This document lists UI comprehensibility and usability improvements across all frontend pages. Each item is scoped as a discrete task.

---

## 1. Macro Monitor — KPI Cards Lack Descriptions

**Page:** `macro.py`
**Problem:** The summary KPI row shows 16+ metric cards with just a value, label, and unit. Users must scroll down to the chart section to learn what each series means. For someone unfamiliar with FRED series, the card wall is opaque.
**Fix:**
- [ ] Add a **tooltip** (dbc.Tooltip or title attribute) to each KPI card that shows the `desc` text already defined in `_SERIES`.
- [ ] Alternatively, add a small `ⓘ` icon on each card that expands an inline description on click.

---

## 2. Screener ROK — Missing Metric Descriptions

**Page:** `screener_rok.py`
**Problem:** Screener ROK has the same `headerTooltip` definitions as the US Stock Screener, so column tooltips are present. However, the preset buttons (High Quality, Value, Growth, QT Regime, QE Regime, Recession Defense) have **no explanation** of what filters they apply. Users must click a preset and reverse-engineer the threshold inputs to understand it.
**Fix:**
- [ ] Add a short description below or beside each preset button (e.g., "High Quality: Score ≥ 60, GM ≥ 20%, ROIC ≥ 10%").
- [ ] Or add a tooltip on hover for each preset button summarizing its filter criteria.
- [ ] Apply the same fix to the US Stock Screener (`screener.py`).

---

## 3. ETF Screener — No Metric Descriptions in ETF Mode

**Page:** `etf.py`
**Problem:** In ETF mode, columns like AUM, Expense Ratio, Dividend Yield, and return columns have **no `headerTooltip`**. Stock-mode columns reuse the screener tooltips. ETF-specific metrics are unexplained.
**Fix:**
- [ ] Add `headerTooltip` to ETF-mode columns: AUM ("Total assets under management — larger AUM means more liquid"), Expense Ratio ("Annual fee as % of assets — lower is better; <0.10% is excellent for index ETFs"), Div. Yield, 3M/6M/1Y/3Y Return.

---

## 4. Technical Chart — Indicator Config UX

**Page:** `technical.py`
**Problem:** "Add Indicator" opens a modal, and indicator configuration also opens a modal. This is workable, but:
- After adding an indicator, the user must click the indicator chip to configure it (two-step). This is not obvious.
- There is no drag-to-reorder for indicator chips; reorder depends on add-order.
- No keyboard shortcut to quickly add common indicators.
**Fix:**
- [ ] After adding an indicator, **auto-open the config modal** so users can set parameters immediately.
- [ ] Add a brief instructional hint near the indicator chip bar: "Click an indicator to configure. Drag to reorder."
- [ ] (Low priority) Consider adding a "Quick Add" dropdown for popular presets (e.g., "SMA 20 + SMA 50 + SMA 200").

---

## 5. Zombie Kill List — Severity Score Unexplained

**Page:** `zombies.py`
**Problem:** Each zombie card shows a "Severity" percentage bar (0–100%) but there is no explanation of how severity is computed. Users see "72%" but don't know what drives it.
**Fix:**
- [ ] Add a small info tooltip or legend at the top: "Severity is based on how far each metric exceeds zombie thresholds (negative FCF, interest coverage <1.0x, declining gross margin)."
- [ ] Optionally show per-metric contribution to severity (e.g., "FCF: 40%, Coverage: 32%").

---

## 6. Batch Compare — No Threshold Legend

**Page:** `compare.py`
**Problem:** Cells are colour-coded green/red/neutral but there's no visible legend explaining the thresholds. Users must guess what "good" means for each metric.
**Fix:**
- [ ] Add a collapsible legend/help section explaining colour thresholds (e.g., "Green: ROIC > 10%, Red: ROIC < 0%").
- [ ] Or add `headerTooltip` to each column with the same educational text used in the screener.

---

## 7. Dashboard — Macro Table Raw Values

**Page:** `dashboard.py`
**Problem:** The macro summary table shows raw FRED series values (e.g., "4.33" for Fed Funds Rate) with no formatting, no colour coding, and no context for whether a value is high/low/normal.
**Fix:**
- [ ] Format values with units (e.g., "4.33%" for rates, "$6.7T" for WALCL).
- [ ] Add colour coding for key thresholds (e.g., red VIX > 25, green unemployment < 4%).
- [ ] Add a tooltip or description column explaining each series.

---

## 8. Sidebar Navigation — No Mobile Support

**Page:** `app.py`
**Problem:** The sidebar is 220px fixed width with no collapse/hamburger toggle. On narrow screens or tablets, it consumes too much horizontal space.
**Fix:**
- [ ] Add a hamburger toggle button that collapses the sidebar on screens < 992px.
- [ ] When collapsed, show only icons (no labels) or hide completely with an overlay.

---

## 9. Retirement Planner — Complex Fields Lack Help Text

**Page:** `retirement.py`
**Problem:** Fields like "Cost Basis Ratio", "IRS 401k Limit", "Employer Match %", and "Post-Retirement Real Return" are advanced financial concepts with no inline help.
**Fix:**
- [ ] Add `html.Small()` hint text below complex input fields explaining the concept in one sentence.
- [ ] Or add an `ⓘ` icon with a tooltip next to each label.

---

## 10. Colour Accessibility — Red/Green Only Differentiation

**Cross-cutting**
**Problem:** Good/bad status across all tables (screener, compare, zombies) relies solely on red (#e74c3c) vs green (#2ecc71) colouring. This is invisible to red-green colourblind users (~8% of males).
**Fix:**
- [x] Add secondary visual cues: `fontStyle: 'italic'` applied to all bad-state cells in screener.py, screener_rok.py, and compare.py. Bad cells are now italic + orange; good cells are bold + green — distinguishable without colour perception.
- [x] Zombies: added "Critical / High / Moderate / Low" text label next to the numeric severity score, giving a colour-independent reading of severity.

---

## 11. Economic Calendar — Importance Not Visually Differentiated

**Page:** `calendar.py`
**Problem:** Events have an "importance" field but all events look the same visually. High-impact events (FOMC, NFP) should stand out from low-impact ones.
**Fix:**
- [ ] Colour-code or size event cards by importance (e.g., bold/larger for "High", muted for "Low").
- [ ] Add an importance filter (show only High/Medium events).

---

## 12. Liquidity Dashboard — Redundant with Macro Monitor

**Page:** `liquidity.py`
**Problem:** The Liquidity Dashboard overlaps significantly with the Macro Monitor's "Liquidity" tab. Users may be confused about which page to use.
**Fix:**
- [ ] Add a subtitle or header note: "Focused view — see Macro Monitor for the full picture."
- [ ] Or merge liquidity into Macro Monitor as a default-selected tab and remove the standalone page.
- [ ] At minimum, add a cross-link between the two pages.

---

## 13. News & Sentiment — Sentiment Labels Unexplained

**Page:** `sentiment.py`
**Problem:** News items are tagged "Bullish" / "Bearish" / "Neutral" but there's no explanation of the NLP/heuristic behind the label. Users may not trust or understand the classification.
**Fix:**
- [ ] Add a small legend: "Sentiment is determined by keyword analysis of the headline. Bullish = positive market keywords, Bearish = negative."
- [ ] If a confidence score is available from the backend, display it (e.g., "Bearish (72%)").

---

## Priority Order (suggested)

| Priority | Item | Effort | Impact |
|----------|------|--------|--------|
| P1 | #1 Macro KPI tooltips | Low | High — 16 cards become comprehensible |
| P1 | #2 Preset button descriptions | Low | High — removes guesswork |
| P1 | #6 Compare threshold legend | Low | High — colour coding meaningless without it |
| P2 | #3 ETF column tooltips | Low | Medium |
| P2 | #7 Dashboard macro formatting | Medium | Medium |
| P2 | #5 Zombie severity explanation | Low | Medium |
| P2 | #4 Technical auto-open config | Low | Medium — smoother workflow |
| P3 | #10 Colour accessibility | Medium | Medium — affects ~8% of users |
| P3 | #9 Retirement help text | Medium | Low-Medium |
| P3 | #11 Calendar importance styling | Low | Low |
| P3 | #13 Sentiment label legend | Low | Low |
| P4 | #8 Mobile sidebar | High | Low — most users on desktop |
| P4 | #12 Liquidity page redundancy | Low | Low |
