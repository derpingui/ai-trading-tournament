"""
Trading engine: execute fictitious trades, apply $1 flat transaction cost,
update portfolio state, and emit WebSocket notifications.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from database import Agent, Portfolio, Position, Trade, PortfolioSnapshot, get_session
from market_data import get_single_price, get_quotes

TRANSACTION_COST = 1.0  # $1 flat fee per trade
MAX_POSITION_FRACTION = 0.25  # max 25% of portfolio value in one stock


@dataclass
class TradeResult:
    success: bool
    message: str
    trade_id: Optional[int] = None
    portfolio_value: Optional[float] = None


# Registered callbacks that get called after every successful trade
_trade_callbacks: list[Callable] = []


def register_trade_callback(fn: Callable) -> None:
    _trade_callbacks.append(fn)


def _notify_callbacks(agent_id: int, trade: dict, portfolio_value: float) -> None:
    for cb in _trade_callbacks:
        try:
            if asyncio.iscoroutinefunction(cb):
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(cb(agent_id, trade, portfolio_value))
                else:
                    loop.run_until_complete(cb(agent_id, trade, portfolio_value))
            else:
                cb(agent_id, trade, portfolio_value)
        except Exception:
            pass


def execute_trade(
    agent_id: int,
    symbol: str,
    action: str,
    quantity: float,
    reasoning: str = "",
    triggered_by: str = "manual",
    price_override: Optional[float] = None,
) -> TradeResult:
    """
    Execute a buy or sell for agent_id.
    - Fetches live price unless price_override is given (for testing).
    - Applies $1 transaction cost.
    - Validates cash/position constraints.
    - Updates Portfolio + Position tables atomically.
    """
    action = action.lower()
    if action not in ("buy", "sell"):
        return TradeResult(success=False, message=f"Invalid action '{action}'")
    if quantity <= 0:
        return TradeResult(success=False, message="Quantity must be positive")

    price = price_override if price_override is not None else get_single_price(symbol)
    if price is None:
        return TradeResult(success=False, message=f"Could not fetch price for {symbol}")

    trade_value = price * quantity

    with get_session() as session:
        portfolio = session.query(Portfolio).filter_by(agent_id=agent_id).first()
        if not portfolio:
            return TradeResult(success=False, message="Agent portfolio not found")

        if action == "buy":
            total_cost = trade_value + TRANSACTION_COST
            if portfolio.cash < total_cost:
                return TradeResult(
                    success=False,
                    message=f"Insufficient cash: need ${total_cost:.2f}, have ${portfolio.cash:.2f}",
                )
            # Check position concentration — clamp to max allowed qty rather than reject
            current_value = _portfolio_value_in_session(session, agent_id, portfolio.cash)
            max_trade_value = current_value * MAX_POSITION_FRACTION
            if trade_value > max_trade_value:
                quantity = max(1, int(max_trade_value / price))
                trade_value = price * quantity
                total_cost = trade_value + TRANSACTION_COST
                if portfolio.cash < total_cost:
                    return TradeResult(success=False, message="Insufficient cash after position-size clamp")

            portfolio.cash -= total_cost
            position = session.query(Position).filter_by(agent_id=agent_id, symbol=symbol).first()
            if position:
                total_qty = position.quantity + quantity
                position.avg_cost = (position.avg_cost * position.quantity + price * quantity) / total_qty
                position.quantity = total_qty
            else:
                session.add(Position(agent_id=agent_id, symbol=symbol, quantity=quantity, avg_cost=price))

        else:  # sell
            position = session.query(Position).filter_by(agent_id=agent_id, symbol=symbol).first()
            if not position or position.quantity < quantity:
                held = position.quantity if position else 0
                return TradeResult(
                    success=False,
                    message=f"Cannot sell {quantity} {symbol}: only hold {held}",
                )
            position.quantity -= quantity
            if position.quantity < 0.0001:
                session.delete(position)
            portfolio.cash += trade_value - TRANSACTION_COST

        portfolio.updated_at = datetime.now(timezone.utc)

        trade = Trade(
            agent_id=agent_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            transaction_cost=TRANSACTION_COST,
            reasoning=reasoning,
            triggered_by=triggered_by,
            timestamp=datetime.now(timezone.utc),
        )
        session.add(trade)
        session.flush()
        trade_id = trade.id

        new_value = _portfolio_value_in_session(session, agent_id, portfolio.cash)
        snapshot = PortfolioSnapshot(
            agent_id=agent_id,
            total_value=new_value,
            timestamp=datetime.now(timezone.utc),
        )
        session.add(snapshot)
        session.commit()

        trade_dict = {
            "id": trade_id,
            "agent_id": agent_id,
            "symbol": symbol,
            "action": action,
            "quantity": quantity,
            "price": price,
            "transaction_cost": TRANSACTION_COST,
            "reasoning": reasoning,
            "triggered_by": triggered_by,
            "timestamp": trade.timestamp.isoformat(),
        }

    _notify_callbacks(agent_id, trade_dict, new_value)
    return TradeResult(success=True, message="Trade executed", trade_id=trade_id, portfolio_value=new_value)


def _portfolio_value_in_session(session: Session, agent_id: int, cash: float) -> float:
    """Compute total portfolio value using cached prices inside an open session."""
    positions = session.query(Position).filter_by(agent_id=agent_id).all()
    if not positions:
        return cash
    symbols = [p.symbol for p in positions]
    quotes = get_quotes(symbols)
    equity = sum(
        p.quantity * (quotes.get(p.symbol, {}).get("price") or p.avg_cost)
        for p in positions
    )
    return cash + equity


def get_portfolio_value(agent_id: int) -> float:
    with get_session() as session:
        portfolio = session.query(Portfolio).filter_by(agent_id=agent_id).first()
        if not portfolio:
            return 0.0
        return _portfolio_value_in_session(session, agent_id, portfolio.cash)


def get_portfolio_snapshot(agent_id: int) -> dict:
    """Return full portfolio state for AI prompt context."""
    with get_session() as session:
        agent = session.query(Agent).filter_by(id=agent_id).first()
        portfolio = session.query(Portfolio).filter_by(agent_id=agent_id).first()
        if not portfolio:
            return {}
        positions = session.query(Position).filter_by(agent_id=agent_id).all()
        symbols = [p.symbol for p in positions]
        quotes = get_quotes(symbols) if symbols else {}

        positions_list = []
        equity = 0.0
        for p in positions:
            current_price = quotes.get(p.symbol, {}).get("price") or p.avg_cost
            market_value = p.quantity * current_price
            equity += market_value
            pnl = market_value - p.quantity * p.avg_cost
            positions_list.append({
                "symbol": p.symbol,
                "quantity": p.quantity,
                "avg_cost": p.avg_cost,
                "current_price": current_price,
                "market_value": market_value,
                "unrealized_pnl": round(pnl, 2),
                "change_pct": quotes.get(p.symbol, {}).get("change_pct", 0),
            })

        total_value = portfolio.cash + equity
        return_pct = ((total_value - portfolio.starting_cash) / portfolio.starting_cash) * 100

        return {
            "agent_name": agent.name if agent else str(agent_id),
            "cash": round(portfolio.cash, 2),
            "equity": round(equity, 2),
            "total_value": round(total_value, 2),
            "starting_cash": portfolio.starting_cash,
            "return_pct": round(return_pct, 2),
            "positions": positions_list,
        }


def get_leaderboard() -> list[dict]:
    with get_session() as session:
        agents = session.query(Agent).filter_by(active=1).all()
        results = []
        for agent in agents:
            snap = get_portfolio_snapshot(agent.id)
            trade_count = session.query(Trade).filter_by(agent_id=agent.id).count()
            results.append({
                "agent_id": agent.id,
                "name": agent.name,
                "model_id": agent.model_id,
                "color": agent.color,
                "total_value": snap.get("total_value", 0),
                "return_pct": snap.get("return_pct", 0),
                "cash": snap.get("cash", 0),
                "trade_count": trade_count,
            })
        results.sort(key=lambda x: x["total_value"], reverse=True)
        for i, r in enumerate(results):
            r["rank"] = i + 1
        return results
