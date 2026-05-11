"""
Gemini trading agent using the new google-genai SDK.
Model: gemini-2.0-flash — free tier via Google AI Studio key.
Get a key at: https://aistudio.google.com/apikey
"""
from __future__ import annotations
import json
import os
import re

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from agents.base_agent import BaseAgent, TradeDecision

SYSTEM_PROMPT = """You are Gemini, an AI portfolio manager competing in a paper trading tournament against other AI models.

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

MODEL_ID = "gemini-2.0-flash"


class GeminiAgent(BaseAgent):
    def __init__(self, agent_id: int):
        super().__init__(agent_id=agent_id, name="Gemini")
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))

    def get_decisions(self, context: str) -> tuple[list[TradeDecision], str]:
        try:
            response = self._client.models.generate_content(
                model=MODEL_ID,
                contents=f"Here is the current market situation. Analyze it and decide on trades:\n\n{context}",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.7,
                    max_output_tokens=1024,
                ),
            )
            raw = response.text.strip()
        except Exception as e:
            return [], f"Gemini API error: {e}"

        return _parse_response(raw)


def _parse_response(raw: str) -> tuple[list[TradeDecision], str]:
    """Extract JSON from Gemini's response, tolerating markdown code fences."""
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
