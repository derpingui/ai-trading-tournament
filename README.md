# 🏆 AI Trading Tournament

> **Can AI models beat each other in the stock market?**
>
> A live paper trading competition where Claude, Llama, Gemini and other AI models each manage a $10,000 portfolio — same budget, same data, same rules. May the best model win.

![Dashboard Preview](https://img.shields.io/badge/Status-Live-22d3a1?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-6366f1?style=for-the-badge)

---

## 🎯 What Is This?

The AI Trading Tournament is a **real-time paper trading dashboard** where multiple AI language models compete head-to-head as portfolio managers. Each AI:

- Starts with **$10,000 in fictional cash**
- Receives identical **live market data** (real prices, real news)
- Pays **$1 flat transaction cost** per trade — same for everyone
- Makes autonomous buy/sell decisions using its own reasoning
- Competes to **maximise total portfolio value** over time

All trades are fictitious — no real money is ever moved. But the market data, news, and prices are 100% real.

---

## 🤖 The Competitors

| Agent | Model | Provider | Status |
|-------|-------|----------|--------|
| 🟠 **Claude** | claude-sonnet-4-6 | Anthropic | Needs API key |
| 🔵 **Gemini** | gemini-2.0-flash | Google | EU restricted (free tier) |
| 🟢 **Llama** | llama-3.3-70b-versatile | Groq | ✅ Active |

Each AI receives the exact same prompt at the same time: current prices, day % changes, recent financial news, and its own portfolio state. It then responds with a structured JSON decision — which stocks to buy or sell and why.

---

## 🏗️ How It Works

### The Decision Cycle

```
Market Data (Twelve Data API)
        +
Financial News (Finnhub API)
        +
Portfolio State (SQLite DB)
        ↓
  AI Prompt (identical for all)
        ↓
  JSON Response: { "analysis": "...", "trades": [...] }
        ↓
  Trading Engine → Executes trades, deducts $1 fee
        ↓
  Dashboard updates in real time (WebSocket)
```

### When Does It Trade?

The scheduler automatically triggers analysis cycles:

| Trigger | When |
|---------|------|
| **Market Open** | 9:30 AM ET, Mon–Fri |
| **Intraday** | Every 30 minutes during market hours |
| **Breaking News** | When Finnhub detects significant news matching current holdings |
| **Manual** | Click "Run Analysis" on the dashboard anytime |

### Competition Rules

1. **Equal starting conditions** — every AI begins with exactly $10,000
2. **Same information** — all AIs receive identical market data and news at the same time
3. **Same costs** — $1 flat transaction fee per trade, applied to everyone
4. **No shorting** — long positions only
5. **Position limits** — max 25% of portfolio value in any single stock (auto-clamped)
6. **Real prices** — trades execute at live market prices from Twelve Data
7. **Permanent history** — all trades, reasoning, and portfolio snapshots are stored forever

---

## 📊 Dashboard Features

- **Leaderboard cards** — live portfolio value, % return, trade count per AI
- **Performance chart** — portfolio value over time, one line per AI
- **Live trade feed** — every trade with the AI's reasoning visible
- **Positions table** — current holdings, entry price, unrealised P&L
- **Market status** — shows whether US markets are currently open
- **WebSocket** — all panels update in real time without page refresh

---

## 🚀 Getting Started

### Requirements

- Python 3.12+
- Free API keys (all take ~30 seconds to get):
  - **Twelve Data** — [twelvedata.com](https://twelvedata.com) (market data, 800 calls/day free)
  - **Finnhub** — [finnhub.io](https://finnhub.io) (financial news, free)
  - **Groq** — [console.groq.com](https://console.groq.com) (Llama inference, free, no EU restrictions)
  - **Anthropic** *(optional)* — [console.anthropic.com](https://console.anthropic.com) (Claude, pay-per-use)

### Installation

```bash
git clone https://github.com/derpingui/ai-trading-tournament.git
cd ai-trading-tournament

pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:

```env
ANTHROPIC_API_KEY=        # optional — enables Claude agent
FINNHUB_API_KEY=          # required — financial news
TWELVE_DATA_API_KEY=      # required — stock prices
GROQ_API_KEY=             # required — enables Llama agent
GEMINI_API_KEY=           # optional — EU users: free tier blocked by Google
```

### Run

```bash
./start.sh
```

Open **http://localhost:8000** in your browser. Click **Run Analysis** to trigger the first round of trades.

---

## 🧩 Architecture

```
ai-trading-tournament/
├── backend/
│   ├── main.py              # FastAPI app + WebSocket server
│   ├── database.py          # SQLite schema (Agent, Portfolio, Position, Trade)
│   ├── market_data.py       # Twelve Data API — real-time stock prices
│   ├── news.py              # Finnhub API — financial news feed
│   ├── trading_engine.py    # Trade execution, $1 cost, portfolio math
│   ├── scheduler.py         # APScheduler — market-hours automation
│   └── agents/
│       ├── base_agent.py    # Abstract agent (add new AIs here)
│       ├── claude_agent.py  # Anthropic SDK — Claude Sonnet
│       ├── gemini_agent.py  # Google GenAI SDK — Gemini 2.0 Flash
│       └── groq_agent.py    # Groq SDK — Llama 3.3 70B
├── frontend/
│   └── index.html           # Single-file dashboard (Chart.js, WebSocket)
├── .env.example
├── requirements.txt
└── start.sh
```

### Adding a New AI Competitor

It takes about 10 lines of code. Create `backend/agents/my_agent.py`:

```python
from agents.base_agent import BaseAgent, TradeDecision

class MyAgent(BaseAgent):
    def __init__(self, agent_id: int):
        super().__init__(agent_id=agent_id, name="MyAI")
        # initialise your SDK client here

    def get_decisions(self, context: str) -> tuple[list[TradeDecision], str]:
        # call your AI with `context`, parse response, return decisions
        ...
```

Then add a row to `database.py` seed list and wire it into `main.py` and `scheduler.py` — that's it.

---

## 📈 Tradeable Universe

The AIs can trade the following symbols:

| Stocks | ETFs |
|--------|------|
| AAPL, MSFT, NVDA, TSLA, GOOGL, META, AMZN, JPM, V | SPY, QQQ |

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI + Uvicorn |
| Database | SQLite + SQLAlchemy |
| Market Data | Twelve Data API |
| News | Finnhub API |
| AI (Llama) | Groq API |
| AI (Claude) | Anthropic API |
| AI (Gemini) | Google GenAI API |
| Automation | APScheduler |
| Frontend | Vanilla JS + Chart.js |
| Real-time | WebSockets |

---

## 🗺️ Roadmap

- [ ] Add OpenAI GPT-4o agent
- [ ] Add Mistral agent
- [ ] Historical backtesting mode
- [ ] Multi-currency support (€, £)
- [ ] Public leaderboard / hosted version
- [ ] Email/push alerts on big trades
- [ ] Crypto market support (24/7)

---

## 📄 License

MIT — do whatever you want with it.

---

*Built with Claude Code. All trades are paper/fictional. Not financial advice.*
