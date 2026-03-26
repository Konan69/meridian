"""LLM-powered agent decisions via OpenCode Zen (OpenAI-compatible API)."""

import asyncio
import json
import logging
import os
import re
from typing import Optional

from openai import AsyncOpenAI

from .types import PROTOCOL_FEE_FORMULAS, PROTOCOL_TRAITS, Protocol

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://opencode.ai/zen/v1"
DEFAULT_MODEL = "minimax-m2.5"
MAX_CONCURRENT = 5  # conservative for free tier rate limits
REQUEST_TIMEOUT = 30


def _build_system_prompt(agent: dict, available_protocols: list[str]) -> str:
    proto_info = []
    for p in available_protocols:
        try:
            proto_enum = Protocol(p)
            traits = PROTOCOL_TRAITS.get(proto_enum, {})
            fee_fn = PROTOCOL_FEE_FORMULAS.get(proto_enum)
            fee_example = f"~{fee_fn(1000)} cents on $10" if fee_fn else "unknown"
            proto_info.append(
                f"- {p.upper()}: micropay={traits.get('supports_micropay', '?')}, "
                f"settlement={traits.get('settlement_ms', '?')}ms, fee={fee_example}"
            )
        except ValueError:
            proto_info.append(f"- {p.upper()}: no details")

    return f"""You are {agent["name"]}, a shopping agent.

Profile: budget=${agent["remaining_budget"] / 100:.2f} remaining, price_sensitivity={agent["price_sensitivity"]:.2f}, preferred=[{", ".join(agent.get("preferred_categories", []))}]

Protocols:
{chr(10).join(proto_info)}

RESPOND WITH ONLY THIS JSON (no other text):
{{"buy": true, "protocol": "x402", "reasoning": "short reason"}}
or
{{"buy": false, "protocol": "", "reasoning": "short reason"}}"""


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Markdown fenced
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Find any JSON object in text
    for m in re.finditer(r'\{[^{}]*"buy"[^{}]*\}', text, re.DOTALL):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    # Last resort: find any { ... }
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


class LLMDecisionEngine:
    """Makes LLM-powered purchase decisions using the OpenAI SDK."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self.total_requests = 0
        self.total_tokens = 0
        self.failed_requests = 0

    async def decide(
        self,
        agent: dict,
        product: dict,
        protocols: list[str],
        rng,
    ) -> dict:
        """Make a purchase decision. Falls back to rule-based on failure."""
        async with self.semaphore:
            try:
                return await self._call_llm(agent, product, protocols)
            except Exception as e:
                self.failed_requests += 1
                logger.debug(f"LLM failed for {agent['name']}: {e}")
                return self._rule_based_fallback(agent, product, protocols, rng)

    async def _call_llm(self, agent: dict, product: dict, protocols: list[str]) -> dict:
        self.total_requests += 1

        system_prompt = _build_system_prompt(agent, protocols)
        user_msg = (
            f"Product: {product.get('name', '?')} "
            f"${product.get('price', 0) / 100:.2f} "
            f"({product.get('category', '?')})"
        )

        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            temperature=0.7,
        )

        if resp.usage:
            self.total_tokens += resp.usage.total_tokens

        # Extract content — handle reasoning models
        content = resp.choices[0].message.content or ""

        # Some models put reasoning in a separate field
        msg = resp.choices[0].message
        if not content and hasattr(msg, "reasoning") and msg.reasoning:
            content = msg.reasoning
        if not content and hasattr(msg, "reasoning_content") and msg.reasoning_content:
            content = msg.reasoning_content

        parsed = _extract_json(content)
        if parsed is None:
            raise ValueError(f"No JSON in response: {content[:100]}")

        result = {
            "buy": bool(parsed.get("buy", False)),
            "protocol": str(parsed.get("protocol", "")),
            "reasoning": str(parsed.get("reasoning", "")),
        }

        # Validate protocol
        if result["buy"] and result["protocol"] not in protocols:
            result["protocol"] = protocols[0] if protocols else "acp"

        return result

    def _rule_based_fallback(
        self, agent: dict, product: dict, protocols: list[str], rng
    ) -> dict:
        """Rule-based decision matching AgentProfile.wants_to_buy() logic."""
        price = product.get("price", 0)
        remaining = agent.get("remaining_budget", 0)

        if price > remaining:
            return {"buy": False, "protocol": "", "reasoning": "over budget"}

        price_sensitivity = agent.get("price_sensitivity", 0.5)
        if price_sensitivity > 0.7 and price > agent.get("budget", remaining) * 0.3:
            if rng.random() > price_sensitivity:
                return {
                    "buy": False,
                    "protocol": "",
                    "reasoning": "price too sensitive",
                }

        buy_prob = 0.5 + (agent.get("risk_tolerance", 0.5) - 0.5) * 0.3
        buy = rng.random() < buy_prob
        proto = rng.choice(protocols) if protocols else "acp"
        return {"buy": buy, "protocol": proto, "reasoning": "rule-based fallback"}

    def stats(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "failed_requests": self.failed_requests,
        }
