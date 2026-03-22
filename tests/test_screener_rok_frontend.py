"""
tests/test_screener_rok_frontend.py
====================================
TDD tests for the ROK Dash frontend page.

Run with::

    pytest tests/test_screener_rok_frontend.py -v
"""

from __future__ import annotations

import sys
import importlib

import dash
import pytest


# ---------------------------------------------------------------------------
# Shared fixture: a minimal Dash app so register_page() doesn't raise
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def dash_app():
    """Instantiate a minimal multi-page Dash app so that dash.register_page()
    calls inside page modules succeed during import."""
    app = dash.Dash(__name__, use_pages=True, pages_folder="")
    return app


# ---------------------------------------------------------------------------
# Step 4 — ROK page imports cleanly and exposes a layout
# ---------------------------------------------------------------------------

class TestScreenerROKPageModule:
    def test_module_imports_without_error(self):
        sys.modules.pop("frontend.pages.screener_rok", None)
        mod = importlib.import_module("frontend.pages.screener_rok")
        assert mod is not None

    def test_layout_is_a_dash_component(self):
        from frontend.pages import screener_rok
        from dash.development.base_component import Component
        assert isinstance(screener_rok.layout, Component)


# ---------------------------------------------------------------------------
# Step 5 — Layout contains exchange selector (.KS / .KQ)
# ---------------------------------------------------------------------------

def _find_by_id(component, target_id):
    """Recursively search a Dash component tree for a component with the given id."""
    if getattr(component, 'id', None) == target_id:
        return component
    children = getattr(component, 'children', None)
    if children is None:
        return None
    if isinstance(children, str):
        return None
    # children can be a single component or a list
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        if not isinstance(child, str):
            result = _find_by_id(child, target_id)
            if result is not None:
                return result
    return None


class TestScreenerROKExchangeSelector:
    def test_layout_contains_exchange_suffix_component(self):
        from frontend.pages import screener_rok
        component = _find_by_id(screener_rok.layout, "rok-exchange-suffix")
        assert component is not None, "No component with id='rok-exchange-suffix' found in layout"

    def test_exchange_suffix_has_ks_option(self):
        from frontend.pages import screener_rok
        component = _find_by_id(screener_rok.layout, "rok-exchange-suffix")
        assert component is not None
        values = [opt["value"] for opt in component.options]
        assert ".KS" in values

    def test_exchange_suffix_has_kq_option(self):
        from frontend.pages import screener_rok
        component = _find_by_id(screener_rok.layout, "rok-exchange-suffix")
        assert component is not None
        values = [opt["value"] for opt in component.options]
        assert ".KQ" in values


# ---------------------------------------------------------------------------
# Step 6 — Suffix helper + api_client region param
# ---------------------------------------------------------------------------

class TestBuildKrxTickers:
    def test_appends_suffix_to_bare_ticker(self):
        from frontend.pages.screener_rok import _build_krx_tickers
        assert _build_krx_tickers("005930", ".KS") == ["005930.KS"]

    def test_no_double_suffix_ks(self):
        from frontend.pages.screener_rok import _build_krx_tickers
        assert _build_krx_tickers("005930.KS", ".KS") == ["005930.KS"]

    def test_keeps_existing_suffix_different_from_selected(self):
        from frontend.pages.screener_rok import _build_krx_tickers
        # .KQ ticker should not get .KS appended even if suffix=.KS
        assert _build_krx_tickers("005930.KQ", ".KS") == ["005930.KQ"]

    def test_multiple_tickers(self):
        from frontend.pages.screener_rok import _build_krx_tickers
        assert _build_krx_tickers("005930, 000660", ".KQ") == ["005930.KQ", "000660.KQ"]

    def test_mixed_tickers(self):
        from frontend.pages.screener_rok import _build_krx_tickers
        result = _build_krx_tickers("005930.KS, 000660", ".KQ")
        assert result == ["005930.KS", "000660.KQ"]


class TestGetScreenerRegionParam:
    def test_get_screener_passes_region_to_http_params(self):
        from unittest.mock import patch, MagicMock
        from frontend.api_client import get_screener

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"rows": [], "meta": {"total": 0}}

        with patch("frontend.api_client.requests.get", return_value=mock_response) as mock_get:
            get_screener(region="rok")
            call_kwargs = mock_get.call_args
            params = call_kwargs[1].get("params") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("params", {})
            # More robust: inspect the params dict passed to requests.get
            params = mock_get.call_args.kwargs.get("params", {})
            assert params.get("region") == "rok"


# ---------------------------------------------------------------------------
# Step 7 — ROK page linked in navbar
# ---------------------------------------------------------------------------

class TestNavbarContainsROKLink:
    def test_nav_items_contains_screener_rok_href(self):
        import importlib
        # Force fresh import to pick up any module-level changes
        import sys
        sys.modules.pop("frontend.app", None)
        mod = importlib.import_module("frontend.app")
        hrefs = [item["href"] for item in mod.NAV_ITEMS]
        assert "/screener-rok" in hrefs

    def test_nav_items_rok_entry_has_nonempty_label(self):
        import importlib
        import sys
        sys.modules.pop("frontend.app", None)
        mod = importlib.import_module("frontend.app")
        entry = next((item for item in mod.NAV_ITEMS if item["href"] == "/screener-rok"), None)
        assert entry is not None
        assert entry.get("label", "").strip() != ""

    def test_nav_items_rok_entry_has_nonempty_icon(self):
        import importlib
        import sys
        sys.modules.pop("frontend.app", None)
        mod = importlib.import_module("frontend.app")
        entry = next((item for item in mod.NAV_ITEMS if item["href"] == "/screener-rok"), None)
        assert entry is not None
        assert entry.get("icon", "").strip() != ""
