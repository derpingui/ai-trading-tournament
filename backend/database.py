from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "trading.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    model_id = Column(String, nullable=False)
    color = Column(String, default="#4f8ef7")
    active = Column(Integer, default=1)

    portfolio = relationship("Portfolio", back_populates="agent", uselist=False)
    positions = relationship("Position", back_populates="agent")
    trades = relationship("Trade", back_populates="agent")
    analyses = relationship("AgentAnalysis", back_populates="agent")


class Portfolio(Base):
    __tablename__ = "portfolios"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), unique=True, nullable=False)
    cash = Column(Float, default=10000.0)
    starting_cash = Column(Float, default=10000.0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    agent = relationship("Agent", back_populates="portfolio")


class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    symbol = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    avg_cost = Column(Float, nullable=False)

    agent = relationship("Agent", back_populates="positions")


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    symbol = Column(String, nullable=False)
    action = Column(String, nullable=False)   # "buy" or "sell"
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    transaction_cost = Column(Float, default=1.0)
    reasoning = Column(Text, default="")
    triggered_by = Column(String, default="manual")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    agent = relationship("Agent", back_populates="trades")


class AgentAnalysis(Base):
    __tablename__ = "agent_analyses"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    market_summary = Column(Text, default="")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    agent = relationship("Agent", back_populates="analyses")


class PortfolioSnapshot(Base):
    """Daily/periodic portfolio value snapshots for the performance chart."""
    __tablename__ = "portfolio_snapshots"
    id = Column(Integer, primary_key=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    total_value = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def init_db():
    Base.metadata.create_all(engine)
    _seed_agents()


def _seed_agents():
    agents_to_seed = [
        {"name": "Claude", "model_id": "claude-sonnet-4-6", "color": "#d97706"},
        {"name": "Gemini", "model_id": "gemini-2.0-flash", "color": "#4285f4"},
        {"name": "Llama", "model_id": "llama-3.3-70b-versatile", "color": "#10b981"},
    ]
    with Session(engine) as session:
        for data in agents_to_seed:
            exists = session.query(Agent).filter_by(name=data["name"]).first()
            if exists:
                continue
            agent = Agent(name=data["name"], model_id=data["model_id"], color=data["color"])
            session.add(agent)
            session.flush()
            portfolio = Portfolio(agent_id=agent.id, cash=10000.0, starting_cash=10000.0)
            session.add(portfolio)
        session.commit()


def get_session() -> Session:
    return Session(engine)


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
    with Session(engine) as s:
        agents = s.query(Agent).all()
        for a in agents:
            print(f"  Agent: {a.name} | model: {a.model_id} | cash: ${a.portfolio.cash:,.2f}")
