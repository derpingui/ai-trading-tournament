"""
Abstract base class for all AI trading agents.
To add a new AI (OpenAI, Gemini, etc.), subclass BaseAgent and implement get_decisions().
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from market_data import get_quotes, get_market_overview, get_tradeable_universe
from news import get_news_for_portfolio, format_news_for_prompt
from trading_engine import execute_trade, get_portfolio_snapshot, TradeResult


@dataclass
class TradeDecision:
    symbol: str
    action: str      # "buy" or "sell"
    quantity: float
    reasoning: str


class BaseAgent(ABC):
    def __init__(self, agent_id: int, name: str):
        self.agent_id = agent_id
        self.name = name

    def build_context(self) -> tuple[str, dict[str, float]]:
        """Assemble market data + news + portfolio state into a prompt-ready string.
        Returns (context_string, price_cache) so execution can reuse fetched prices."""
        portfolio = get_portfolio_snapshot(self.agent_id)
        universe = get_tradeable_universe()

        held_symbols = [p["symbol"] for p in portfolio.get("positions", [])]
        market_quotes = get_quotes(universe)
        market_overview = get_market_overview()
        news_articles = get_news_for_portfolio(held_symbols)
        news_text = format_news_for_prompt(news_articles)

        market_lines = []
        for sym, q in market_quotes.items():
            if q.get("price"):
                chg = q.get("change_pct", 0)
                sign = "+" if chg >= 0 else ""
                market_lines.append(f"  {sym}: ${q['price']:.2f} ({sign}{chg:.2f}%)")
        market_text = "\n".join(market_lines)

        positions_text = "None (all cash)"
        if portfolio.get("positions"):
            pos_lines = []
            for p in portfolio["positions"]:
                pnl_sign = "+" if p["unrealized_pnl"] >= 0 else ""
                pos_lines.append(
                    f"  {p['symbol']}: {p['quantity']:.0f} shares @ ${p['avg_cost']:.2f} "
                    f"| current ${p['current_price']:.2f} "
                    f"| P&L {pnl_sign}${p['unrealized_pnl']:.2f}"
                )
            positions_text = "\n".join(pos_lines)

        vix = (market_overview.get("vix") or {}).get("price", "N/A")
        spy_chg = (market_overview.get("spy") or {}).get("change_pct", "N/A")

        context = f"""=== MARKET SNAPSHOT ===
SPY: {spy_chg:+.2f}% today | VIX: {vix}

=== TRADEABLE UNIVERSE (prices) ===
{market_text}

=== YOUR PORTFOLIO ===
Cash available: ${portfolio['cash']:,.2f}
Equity value:   ${portfolio['equity']:,.2f}
Total value:    ${portfolio['total_value']:,.2f}
Return:         {portfolio['return_pct']:+.2f}% (started at ${portfolio['starting_cash']:,.2f})

=== CURRENT POSITIONS ===
{positions_text}

=== RECENT NEWS ===
{news_text}
"""
        price_cache = {
            sym: data["price"]
            for sym, data in market_quotes.items()
            if data.get("price") is not None
        }
        return context, price_cache

    @abstractmethod
    def get_decisions(self, context: str) -> tuple[list[TradeDecision], str]:
        """
        Parse AI response into trade decisions.
        Returns (list_of_decisions, market_analysis_text).
        """
        ...

    def run_cycle(self, triggered_by: str = "manual") -> dict:
        """
        Full analysis + trade cycle.
        Returns summary dict with decisions made and results.
        """
        context, price_cache = self.build_context()
        decisions, analysis = self.get_decisions(context)

        results = []
        for decision in decisions:
            # Reuse the price already fetched during context building to avoid
            # hitting the Twelve Data rate limit with a second request per trade.
            cached_price = price_cache.get(decision.symbol)
            result: TradeResult = execute_trade(
                agent_id=self.agent_id,
                symbol=decision.symbol,
                action=decision.action,
                quantity=decision.quantity,
                reasoning=decision.reasoning,
                triggered_by=triggered_by,
                price_override=cached_price,
            )
            results.append({
                "symbol": decision.symbol,
                "action": decision.action,
                "quantity": decision.quantity,
                "reasoning": decision.reasoning,
                "success": result.success,
                "message": result.message,
                "portfolio_value": result.portfolio_value,
            })

        # Save analysis to DB
        from database import AgentAnalysis, get_session
        from datetime import datetime, timezone
        with get_session() as session:
            session.add(AgentAnalysis(
                agent_id=self.agent_id,
                market_summary=analysis,
                timestamp=datetime.now(timezone.utc),
            ))
            session.commit()

        return {
            "agent": self.name,
            "analysis": analysis,
            "decisions": results,
            "triggered_by": triggered_by,
        }
