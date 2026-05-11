"""
OpenRouter agent — uses OpenAI-compatible API to access any OpenRouter model.
Current competitor: openai/gpt-oss-120b (free tier).
Get a key at: https://openrouter.ai
"""
from __future__ import annotations
import json
import os
import re

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from agents.base_agent import BaseAgent, TradeDecision

SYSTEM_PROMPT = """You are GPT, an AI portfolio manager competing in a paper trading tournament against other AI models including Claude, Llama, and Gemini.

RULES:
- Starting capital: $10,000. Transaction cost: $1.00 flat per trade.
- Max 25% of total portfolio value in any single position.
- No short selling. No leverage.
- You may hold cash — sometimes doing nothing is the right call.
- Trade from the provided symbol universe only.

YOUR GOAL: Maximize total portfolio value over time. Think like a disciplined investor, not a gambler.

RESPONSE FORMAT:
Always respond with valid JSON only. No markdown, no explanation outside the JSON.

{
  "analysis": "2-3 sentence market outlook and your reasoning",
  "trades": [
    {
      "symbol": "AAPL",
      "action": "buy",
      "quantity": 5,
      "reasoning": "one sentence rationale"
    }
  ]
}

If you decide to make no trades, return an empty trades array:
{"analysis": "...", "trades": []}

IMPORTANT: quantity must be a whole number of shares. Do not exceed your available cash minus $1 per trade."""

MODEL_ID = "openai/gpt-oss-120b:free"


class OpenRouterAgent(BaseAgent):
    def __init__(self, agent_id: int, model_id: str = MODEL_ID, name: str = "GPT"):
        super().__init__(agent_id=agent_id, name=name)
        self._client = OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY", ""),
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/derpingui/ai-trading-tournament",
                "X-Title": "AI Trading Tournament",
            },
        )
        self._model_id = model_id

    def get_decisions(self, context: str) -> tuple[list[TradeDecision], str]:
        try:
            response = self._client.chat.completions.create(
                model=self._model_id,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Here is the current market situation. Analyze it and decide on trades:\n\n{context}"},
                ],
                temperature=0.7,
                max_tokens=1024,
            )
            raw = response.choices[0].message.content.strip()
        except Exception as e:
            return [], f"OpenRouter API error: {e}"

        return _parse_response(raw)


def _parse_response(raw: str) -> tuple[list[TradeDecision], str]:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                return [], f"Failed to parse JSON: {raw[:200]}"
        else:
            return [], f"No JSON found in response: {raw[:200]}"

    analysis = data.get("analysis", "")
    raw_trades = data.get("trades", [])

    decisions = []
    for t in raw_trades:
        sym = str(t.get("symbol", "")).upper().strip()
        action = str(t.get("action", "")).lower().strip()
        try:
            qty = float(t.get("quantity", 0))
        except (TypeError, ValueError):
            continue
        reasoning = str(t.get("reasoning", ""))
        if sym and action in ("buy", "sell") and qty > 0:
            decisions.append(TradeDecision(symbol=sym, action=action, quantity=qty, reasoning=reasoning))

    return decisions, analysis
