# AI Agent Reading Order

**Purpose**: Minimal, strictly-ordered workflow for AI agents entering this codebase.
Reading this sequence first prevents redundant full-codebase scanning.

---

## Strict Reading Sequence

```
Step 1  docs/README.md
Step 2  docs/00_getting_started/repository-summary.md
Step 3  docs/01_architecture/architecture-overview.md
Step 4  docs/01_architecture/data-flow-and-control-flow.md
Step 5  docs/02_modules/module-responsibility-map.md
Step 6  docs/04_maintenance/change-routing-guide.md   ← locates edit targets
Step 7  [ONLY the source files the change-routing guide recommends for your task]
```

**Do not skip to step 7.** Steps 1–6 take under 5 minutes to read and will
prevent reading dozens of source files that are irrelevant to your task.

---

## When to Begin Source Inspection

Begin inspecting source files **only** after:
- You know which feature area the task touches (from step 6).
- The change-routing guide has given you primary and secondary file candidates.
- You need to confirm a function signature, callback ID, or schema field that
  the docs cannot answer with confidence.

### Common task → entry file

| Task type | First source file to open |
|-----------|--------------------------|
| Modify a Dash page layout or callback | `frontend/pages/<page-name>.py` |
| Change a FastAPI endpoint | `src/api/routers/<router>.py` + `src/api/schemas.py` |
| Change a financial metric formula | `src/metrics.py` |
| Change database schema | `src/models.py` → then `src/database.py` |
| Change ingestion / data fetch | `src/ingestion/<source>.py` |
| Add or modify a backtest strategy | `frontend/strategy/engine.py` → `frontend/strategy/builtins/<name>.py` |
| Change config / env vars | `src/config.py` |
| Fix zombie classification | `src/zombie.py` |
| Fix retirement engine | `src/retirement.py` |

---

## Files to Avoid Scanning First

These files are large or generated and should not be opened unless directly implicated:

| File | Size / reason |
|------|---------------|
| `frontend/pages/technical.py` | ~2 100 lines — complex Dash chart page |
| `src/api/schemas.py` | All Pydantic models — read only when schema changes are needed |
| `data/stock_screener.db` | Binary — never read |
| `data/technical_chart/*.json` | Runtime presets — not source code |
| `plan/` | Design notes — useful context but not authoritative source of truth |

---

## Confidence Calibration

- **Confirmed** paths are verified against actual source files.
- **Strong inference** means consistent with README + ARCHITECTURE.md.
- **Weak inference** means based on naming conventions only.
- **Unknown** means the docs are silent; inspect source before acting.
