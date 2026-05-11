"""
Financial news via Finnhub (free tier: 60 req/min).
Falls back to empty list gracefully if API key is missing or quota hit.
"""
from __future__ import annotations
import os
import time
import finnhub
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

_client: finnhub.Client | None = None


def _get_client() -> finnhub.Client | None:
    global _client
    if _client is None:
        key = os.getenv("FINNHUB_API_KEY", "")
        if not key:
            return None
        _client = finnhub.Client(api_key=key)
    return _client


def get_market_news(limit: int = 10) -> list[dict]:
    """General market/economy news from Finnhub."""
    client = _get_client()
    if not client:
        return []
    try:
        articles = client.general_news("general", min_id=0)
        return _format_articles(articles[:limit])
    except Exception:
        return []


def get_company_news(symbol: str, days_back: int = 2) -> list[dict]:
    """News specific to a stock symbol."""
    client = _get_client()
    if not client:
        return []
    try:
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=days_back)
        articles = client.company_news(
            symbol,
            _from=from_date.strftime("%Y-%m-%d"),
            to=to_date.strftime("%Y-%m-%d"),
        )
        return _format_articles(articles[:5])
    except Exception:
        return []


def get_news_for_portfolio(symbols: list[str]) -> list[dict]:
    """
    Fetch news for each held symbol + general market news.
    Returns merged list sorted by datetime, deduped by headline.
    """
    all_articles: list[dict] = get_market_news(limit=8)
    seen_headlines: set[str] = {a["headline"] for a in all_articles}

    for sym in symbols[:5]:   # cap at 5 symbols to respect rate limits
        for article in get_company_news(sym):
            if article["headline"] not in seen_headlines:
                all_articles.append(article)
                seen_headlines.add(article["headline"])
        time.sleep(0.1)  # gentle rate limiting

    all_articles.sort(key=lambda a: a["datetime"], reverse=True)
    return all_articles[:20]


def _format_articles(raw: list[dict]) -> list[dict]:
    out = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        out.append({
            "headline": a.get("headline", ""),
            "summary": a.get("summary", "")[:300],
            "source": a.get("source", ""),
            "url": a.get("url", ""),
            "datetime": a.get("datetime", 0),
            "related": a.get("related", ""),
        })
    return out


def format_news_for_prompt(articles: list[dict]) -> str:
    """Convert article list to a compact string for AI prompts."""
    if not articles:
        return "No recent news available."
    lines = []
    for a in articles[:10]:
        ts = datetime.fromtimestamp(a["datetime"], tz=timezone.utc).strftime("%H:%M UTC") if a["datetime"] else ""
        lines.append(f"- [{a['source']} {ts}] {a['headline']}. {a['summary']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print("Market news:")
    for article in get_market_news(5):
        print(f"  {article['source']}: {article['headline'][:80]}")
