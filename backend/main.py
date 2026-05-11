"""
FastAPI backend: REST endpoints + WebSocket for real-time dashboard updates.
Run with: uvicorn main:app --reload --port 8000
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

sys.path.insert(0, os.path.dirname(__file__))
from database import init_db, get_session, Agent, Trade, AgentAnalysis, PortfolioSnapshot
from trading_engine import (
    get_leaderboard, get_portfolio_snapshot, execute_trade,
    register_trade_callback,
)


# --- WebSocket connection manager ---

class ConnectionManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self.connections.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)


manager = ConnectionManager()


async def _on_trade(agent_id: int, trade: dict, portfolio_value: float):
    """Called by trading_engine after every successful trade."""
    with get_session() as session:
        agent = session.query(Agent).filter_by(id=agent_id).first()
        agent_name = agent.name if agent else str(agent_id)
        agent_color = agent.color if agent else "#888"

    await manager.broadcast({
        "type": "trade_executed",
        "agent_id": agent_id,
        "agent_name": agent_name,
        "agent_color": agent_color,
        "trade": trade,
        "portfolio_value": portfolio_value,
    })
    await manager.broadcast({
        "type": "leaderboard_update",
        "leaderboard": get_leaderboard(),
    })


# --- App lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    register_trade_callback(_on_trade)
    # Start scheduler in background
    from scheduler import start_scheduler
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="AI Trading Tournament", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# --- REST endpoints ---

@app.get("/")
async def root():
    index = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"message": "AI Trading Tournament API", "docs": "/docs"}


@app.get("/leaderboard")
async def leaderboard():
    return get_leaderboard()


@app.get("/portfolio/{agent_id}")
async def portfolio(agent_id: int):
    snap = get_portfolio_snapshot(agent_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Agent not found")
    return snap


@app.get("/trades/{agent_id}")
async def trades(agent_id: int, limit: int = 50):
    with get_session() as session:
        rows = (
            session.query(Trade)
            .filter_by(agent_id=agent_id)
            .order_by(Trade.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": t.id,
                "symbol": t.symbol,
                "action": t.action,
                "quantity": t.quantity,
                "price": t.price,
                "transaction_cost": t.transaction_cost,
                "reasoning": t.reasoning,
                "triggered_by": t.triggered_by,
                "timestamp": t.timestamp.isoformat(),
            }
            for t in rows
        ]


@app.get("/trades")
async def all_trades(limit: int = 100):
    with get_session() as session:
        rows = (
            session.query(Trade, Agent)
            .join(Agent, Trade.agent_id == Agent.id)
            .order_by(Trade.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": t.id,
                "agent_id": t.agent_id,
                "agent_name": a.name,
                "agent_color": a.color,
                "symbol": t.symbol,
                "action": t.action,
                "quantity": t.quantity,
                "price": t.price,
                "transaction_cost": t.transaction_cost,
                "reasoning": t.reasoning,
                "triggered_by": t.triggered_by,
                "timestamp": t.timestamp.isoformat(),
            }
            for t, a in rows
        ]


@app.get("/analysis/{agent_id}")
async def analysis(agent_id: int, limit: int = 10):
    with get_session() as session:
        rows = (
            session.query(AgentAnalysis)
            .filter_by(agent_id=agent_id)
            .order_by(AgentAnalysis.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {"market_summary": r.market_summary, "timestamp": r.timestamp.isoformat()}
            for r in rows
        ]


@app.get("/chart/{agent_id}")
async def chart_data(agent_id: int, limit: int = 200):
    """Portfolio value over time for the performance chart."""
    with get_session() as session:
        rows = (
            session.query(PortfolioSnapshot)
            .filter_by(agent_id=agent_id)
            .order_by(PortfolioSnapshot.timestamp.asc())
            .limit(limit)
            .all()
        )
        return [
            {"timestamp": r.timestamp.isoformat(), "value": r.total_value}
            for r in rows
        ]


@app.get("/chart")
async def all_chart_data(limit: int = 200):
    """Portfolio value snapshots for all agents, grouped by agent."""
    with get_session() as session:
        agents = session.query(Agent).filter_by(active=1).all()
        result = {}
        for agent in agents:
            rows = (
                session.query(PortfolioSnapshot)
                .filter_by(agent_id=agent.id)
                .order_by(PortfolioSnapshot.timestamp.asc())
                .limit(limit)
                .all()
            )
            result[agent.name] = {
                "color": agent.color,
                "data": [{"timestamp": r.timestamp.isoformat(), "value": r.total_value} for r in rows],
            }
        return result


@app.post("/trigger/{agent_id}")
async def trigger_analysis(agent_id: int):
    """Manually trigger one AI analysis + trade cycle."""
    with get_session() as session:
        agent = session.query(Agent).filter_by(id=agent_id).first()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        model_id = agent.model_id
        name = agent.name

    result = await asyncio.get_event_loop().run_in_executor(
        None, _run_agent_cycle, agent_id, model_id, "manual"
    )
    return result


@app.post("/trigger")
async def trigger_all():
    """Trigger analysis cycle for all active agents."""
    with get_session() as session:
        agents = session.query(Agent).filter_by(active=1).all()
        agent_data = [(a.id, a.model_id) for a in agents]

    results = []
    for agent_id, model_id in agent_data:
        r = await asyncio.get_event_loop().run_in_executor(
            None, _run_agent_cycle, agent_id, model_id, "manual"
        )
        results.append(r)
    return results


@app.get("/agents")
async def list_agents():
    with get_session() as session:
        agents = session.query(Agent).filter_by(active=1).all()
        return [
            {"id": a.id, "name": a.name, "model_id": a.model_id, "color": a.color}
            for a in agents
        ]


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    # Send initial state on connect
    await ws.send_text(json.dumps({
        "type": "init",
        "leaderboard": get_leaderboard(),
    }))
    try:
        while True:
            await ws.receive_text()   # keep connection alive; client may send pings
    except WebSocketDisconnect:
        manager.disconnect(ws)


# --- Helpers ---

def _run_agent_cycle(agent_id: int, model_id: str, triggered_by: str) -> dict:
    """Instantiate the right agent class and run one cycle (blocking)."""
    if "claude" in model_id.lower():
        from agents.claude_agent import ClaudeAgent
        agent = ClaudeAgent(agent_id=agent_id)
    elif "gemini" in model_id.lower():
        from agents.gemini_agent import GeminiAgent
        agent = GeminiAgent(agent_id=agent_id)
    elif "llama" in model_id.lower():
        from agents.groq_agent import GroqAgent
        agent = GroqAgent(agent_id=agent_id)
    else:
        return {"error": f"No agent implementation for model_id '{model_id}'"}
    return agent.run_cycle(triggered_by=triggered_by)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
