"""
Market data via Twelve Data (free tier: 800 API calls/day, 8/min).
Free API key at https://twelvedata.com — takes ~20 seconds to get one.
Falls back gracefully when the key is missing or rate-limited.
"""
from __future__ import annotations
import os
import time
import requests
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

BASE_URL = "https://api.twelvedata.com"
DEFAULT_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "TSLA", "GOOGL",
    "META", "AMZN", "JPM", "V",
    "SPY", "QQQ",
]

_session = requests.Session()
_session.headers.update({"User-Agent": "AI-Trading-Tournament/1.0"})


def _api_key() -> str:
    return os.getenv("TWELVE_DATA_API_KEY", "demo")


def _get(endpoint: str, params: dict) -> dict | None:
    params["apikey"] = _api_key()
    try:
        r = _session.get(f"{BASE_URL}/{endpoint}", params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("status") == "error":
            return None
        return data
    except Exception:
        return None


def get_quotes(symbols: list[str]) -> dict[str, dict]:
    """
    Return current price + day change % for each symbol.
    Uses the /quote endpoint (1 API credit per symbol).
    """
    results: dict[str, dict] = {}
    for sym in symbols:
        data = _get("quote", {"symbol": sym})
        if not data or not data.get("close"):
            results[sym] = {"symbol": sym, "price": None, "change_pct": 0}
            time.sleep(0.1)
            continue
        try:
            price = float(data["close"])
            prev = float(data.get("previous_close") or price)
            change_pct = float(data.get("percent_change") or 0)
            results[sym] = {
                "symbol": sym,
                "price": round(price, 4),
                "prev_close": round(prev, 4),
                "change_pct": round(change_pct, 2),
                "volume": data.get("volume"),
                "name": data.get("name", sym),
            }
        except (TypeError, ValueError):
            results[sym] = {"symbol": sym, "price": None, "change_pct": 0}
        time.sleep(0.5)   # conservative pacing: ~6 req/min, safely under the 8/min free limit
    return results


def get_single_price(symbol: str) -> Optional[float]:
    """Fetch a single current price."""
    data = _get("price", {"symbol": symbol})
    if not data or not data.get("price"):
        return None
    try:
        return float(data["price"])
    except (TypeError, ValueError):
        return None


def get_historical(symbol: str, period: str = "30d") -> list[dict]:
    """
    Return daily OHLCV history.
    period: "5d" → outputsize 5, "30d" → 30, "3mo" → 90, "1y" → 252
    """
    period_map = {"5d": 5, "30d": 30, "3mo": 90, "1y": 252}
    outputsize = period_map.get(period, 30)
    data = _get("time_series", {
        "symbol": symbol,
        "interval": "1day",
        "outputsize": outputsize,
        "order": "ASC",
    })
    if not data or not data.get("values"):
        return []
    records = []
    for v in data["values"]:
        try:
            records.append({
                "date": v["datetime"],
                "open": float(v["open"]),
                "high": float(v["high"]),
                "low": float(v["low"]),
                "close": float(v["close"]),
                "volume": int(v.get("volume") or 0),
            })
        except (KeyError, ValueError):
            continue
    return records


def get_market_overview() -> dict:
    """Snapshot of key indices for AI context."""
    index_symbols = ["SPY", "QQQ", "IWM"]
    quotes = get_quotes(index_symbols)
    # VIX via separate call
    vix_data = _get("quote", {"symbol": "VIX"})
    vix_price = None
    if vix_data and vix_data.get("close"):
        try:
            vix_price = float(vix_data["close"])
        except (TypeError, ValueError):
            pass
    return {
        "spy": quotes.get("SPY"),
        "qqq": quotes.get("QQQ"),
        "iwm": quotes.get("IWM"),
        "vix": {"price": vix_price},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_tradeable_universe() -> list[str]:
    return DEFAULT_SYMBOLS


if __name__ == "__main__":
    print("Testing Twelve Data market data...")
    q = get_quotes(["AAPL", "NVDA", "SPY"])
    for sym, data in q.items():
        p = data.get("price")
        chg = data.get("change_pct", 0)
        print(f"  {sym}: ${p} ({chg:+.2f}%)" if p else f"  {sym}: no data")
    print("\nMarket overview:")
    ov = get_market_overview()
    for k, v in ov.items():
        if isinstance(v, dict):
            print(f"  {k}: ${(v or {}).get('price')}")
