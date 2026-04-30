"""Force a full max-history daily OHLCV refresh for all universe tickers."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.ohlcv.store import OHLCVStore
from src.ohlcv.fetcher import OHLCVFetcher
from src.scanner.universe import resolve_universe
from src.config import settings

store = OHLCVStore(settings.ohlcv_dir)
fetcher = OHLCVFetcher(store, stale_hours=0)
tickers = resolve_universe().tickers
print(f"Fetching max history for {len(tickers)} tickers ...")
r = fetcher.sync_daily(tickers, force_full=True)
print(f"ok={len(r.succeeded)} fail={len(r.failed)} skip={len(r.skipped)}")
if r.failed:
    print("Failed:", r.failed)
