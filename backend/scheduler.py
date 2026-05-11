"""
APScheduler automation:
- Market open (9:30 AM ET): trigger all agents
- Every 30 min during market hours: trigger all agents
- Every 15 min: poll news and trigger if significant event found
- Market close (4:00 PM ET): end-of-day snapshot
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

sys.path.insert(0, os.path.dirname(__file__))

logger = logging.getLogger(__name__)

_last_seen_news_ids: set[int] = set()


def _run_all_agents(triggered_by: str = "scheduler") -> None:
    from database import Agent, get_session
    from agents.claude_agent import ClaudeAgent

    with get_session() as session:
        agents = session.query(Agent).filter_by(active=1).all()
        agent_data = [(a.id, a.model_id) for a in agents]

    for agent_id, model_id in agent_data:
        try:
            if "claude" in model_id.lower():
                agent = ClaudeAgent(agent_id=agent_id)
            elif "gemini" in model_id.lower():
                from agents.gemini_agent import GeminiAgent
                agent = GeminiAgent(agent_id=agent_id)
            elif "llama" in model_id.lower():
                from agents.groq_agent import GroqAgent
                agent = GroqAgent(agent_id=agent_id)
            elif "gpt-oss" in model_id.lower():
                from agents.openrouter_agent import OpenRouterAgent
                agent = OpenRouterAgent(agent_id=agent_id, model_id=model_id, name="GPT")
            else:
                logger.warning("No agent implementation for model_id '%s'", model_id)
                continue
            if agent:
                result = agent.run_cycle(triggered_by=triggered_by)
                logger.info(
                    "Agent %s completed cycle: %d decisions",
                    result.get("agent"),
                    len(result.get("decisions", [])),
                )
        except Exception as e:
            logger.error("Agent %d error: %s", agent_id, e)


def _check_news_trigger() -> None:
    """
    Poll news. If a new article mentions a significant index move or
    matches a current holding, trigger an out-of-schedule analysis.
    """
    global _last_seen_news_ids
    from news import get_market_news
    from database import Position, get_session

    try:
        articles = get_market_news(limit=20)
    except Exception:
        return

    with get_session() as session:
        held = {p.symbol for p in session.query(Position).all()}

    new_significant = []
    for a in articles:
        aid = a.get("datetime", 0)
        if aid in _last_seen_news_ids:
            continue
        _last_seen_news_ids.add(aid)

        headline = (a.get("headline") or "").lower()
        related = (a.get("related") or "").upper()

        # Trigger if headline mentions a large market move
        is_market_move = any(w in headline for w in ["crash", "surge", "plunge", "rally", "fed", "rate hike", "recession"])
        is_holding = any(sym in related for sym in held)

        if is_market_move or is_holding:
            new_significant.append(a.get("headline", ""))

    if new_significant:
        logger.info("News trigger fired: %s", new_significant[0][:80])
        _run_all_agents(triggered_by="news")

    # Keep set bounded
    if len(_last_seen_news_ids) > 10000:
        _last_seen_news_ids = set(list(_last_seen_news_ids)[-5000:])


def _market_open() -> None:
    logger.info("Market open — running all agents")
    _run_all_agents(triggered_by="market_open")


def _intraday() -> None:
    if not _is_market_hours():
        return
    logger.info("Intraday trigger — running all agents")
    _run_all_agents(triggered_by="intraday")


def _market_close() -> None:
    logger.info("Market close — saving end-of-day snapshots")
    _save_eod_snapshots()


def _save_eod_snapshots() -> None:
    from database import Agent, PortfolioSnapshot, get_session
    from trading_engine import get_portfolio_value
    from datetime import timezone

    with get_session() as session:
        agents = session.query(Agent).filter_by(active=1).all()
        for agent in agents:
            value = get_portfolio_value(agent.id)
            session.add(PortfolioSnapshot(
                agent_id=agent.id,
                total_value=value,
                timestamp=datetime.now(timezone.utc),
            ))
        session.commit()


def _is_market_hours() -> bool:
    """Basic check: Mon–Fri 9:30–16:00 Eastern."""
    try:
        import exchange_calendars as xcals
        cal = xcals.get_calendar("XNYS")
        now = datetime.now(timezone.utc)
        return cal.is_open_on_minute(now)
    except Exception:
        # Fallback: weekday + rough UTC time check (14:30–21:00 UTC = 9:30-16:00 ET)
        now = datetime.now(timezone.utc)
        if now.weekday() >= 5:
            return False
        return 14 <= now.hour < 21


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="America/New_York")

    # Market open: 9:30 AM ET, Mon–Fri
    scheduler.add_job(
        _market_open,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=30, timezone="America/New_York"),
        id="market_open",
        replace_existing=True,
    )

    # Intraday every 30 min during market hours
    scheduler.add_job(
        _intraday,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="0,30", timezone="America/New_York"),
        id="intraday",
        replace_existing=True,
    )

    # Market close: 4:00 PM ET, Mon–Fri
    scheduler.add_job(
        _market_close,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0, timezone="America/New_York"),
        id="market_close",
        replace_existing=True,
    )

    # News polling every 15 min, always running
    scheduler.add_job(
        _check_news_trigger,
        CronTrigger(minute="*/15"),
        id="news_poll",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started")
    return scheduler
