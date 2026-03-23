"""LLM-powered agent decisions via OpenCode Zen API."""

import asyncio
import json
import logging
import os
import re
from typing import Optional

import aiohttp

from .types import PROTOCOL_FEE_FORMULAS, PROTOCOL_TRAITS, Protocol

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://opencode.ai/zen/v1/chat/completions"
DEFAULT_MODEL = "minimax-m2.5-free"
MAX_CONCURRENT = 10
REQUEST_TIMEOUT = 30


def _build_system_prompt(agent: dict, available_protocols: list[str]) -> str:
    """Build a system prompt that establishes the agent persona."""
    proto_info = []
    for p in available_protocols:
        try:
            proto_enum = Protocol(p)
            traits = PROTOCOL_TRAITS.get(proto_enum, {})
            fee_fn = PROTOCOL_FEE_FORMULAS.get(proto_enum)
            fee_example = f"~{fee_fn(1000)} cents on $10" if fee_fn else "unknown"
            proto_info.append(
                f"- {p.upper()}: micropay={traits.get('supports_micropay', '?')}, "
                f"settlement={traits.get('settlement_ms', '?')}ms, "
                f"autonomy={traits.get('autonomy', '?')}, fee={fee_example}"
            )
        except ValueError:
            proto_info.append(f"- {p.upper()}: no details available")

    return f"""You are {agent['name']}, an AI shopping agent in a commerce simulation.

Your profile:
- Total budget: ${agent['budget'] / 100:.2f}
- Remaining budget: ${agent['remaining_budget'] / 100:.2f}
- Price sensitivity: {agent['price_sensitivity']:.2f} (0=doesn't care, 1=very price-conscious)
- Brand loyalty: {agent['brand_loyalty']:.2f} (0=tries anything, 1=sticks to favorites)
- Preferred categories: {', '.join(agent.get('preferred_categories', ['any']))}

Available payment protocols:
{chr(10).join(proto_info)}

You must respond with ONLY a JSON object (no markdown, no explanation outside the JSON):
{{"buy": true/false, "protocol": "<protocol_name>", "reasoning": "<1-2 sentence explanation>"}}

Choose the protocol that best fits the transaction based on your persona, the product, and protocol characteristics."""


def _build_user_prompt(product: dict) -> str:
    """Build the user prompt describing the product."""
    return (
        f"Should you buy this product?\n"
        f"Name: {product.get('name', 'Unknown')}\n"
        f"Price: ${product.get('price', 0) / 100:.2f}\n"
        f"Category: {product.get('category', 'unknown')}\n"
        f"Description: {product.get('description', 'No description')}"
    )


def _extract_json(text: str) -> Optional[dict]:
    """Extract a JSON object from LLM response text, handling markdown fences."""
    if not text:
        return None
    # Try direct parse first
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding first { ... } pair
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _parse_llm_response(response_json: dict) -> dict:
    """Parse the API response, handling reasoning models where content may be null."""
    choices = response_json.get("choices", [])
    if not choices:
        raise ValueError("No choices in API response")

    message = choices[0].get("message", {})
    content = message.get("content")
    reasoning = message.get("reasoning") or message.get("reasoning_details") or message.get("reasoning_content")

    # Try content first, then reasoning field
    text = content or reasoning or ""
    if isinstance(text, list):
        # Some models return reasoning as a list of objects
        text = " ".join(
            item.get("content", str(item)) if isinstance(item, dict) else str(item)
            for item in text
        )

    parsed = _extract_json(text)
    if parsed is None:
        raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")

    return {
        "buy": bool(parsed.get("buy", False)),
        "protocol": str(parsed.get("protocol", "")),
        "reasoning": str(parsed.get("reasoning", "No reasoning provided")),
    }


async def llm_purchase_decision(
    agent_profile: dict,
    product: dict,
    available_protocols: list[str],
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    api_url: str = DEFAULT_API_URL,
) -> dict:
    """Make an LLM-powered purchase decision for an agent.

    Args:
        agent_profile: Agent persona dict with name, budget, remaining_budget,
                       price_sensitivity, brand_loyalty, preferred_categories.
        product: Product dict with name, price, category, description.
        available_protocols: List of protocol name strings (e.g. ["acp", "x402"]).
        api_key: OpenCode API key. Falls back to OPENCODE_API_KEY env var.
        model: Model identifier for the API.
        api_url: API endpoint URL.

    Returns:
        {"buy": bool, "protocol": str, "reasoning": str}
    """
    key = api_key or os.environ.get("OPENCODE_API_KEY", "")
    if not key:
        raise ValueError("No API key provided and OPENCODE_API_KEY not set")

    system_prompt = _build_system_prompt(agent_profile, available_protocols)
    user_prompt = _build_user_prompt(product)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 256,
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(api_url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise ValueError(f"API returned {resp.status}: {body[:300]}")
            data = await resp.json()

    result = _parse_llm_response(data)

    # Validate protocol is in available list
    if result["protocol"] not in available_protocols:
        # Pick first available as fallback
        result["protocol"] = available_protocols[0] if available_protocols else ""
        result["reasoning"] += " (protocol corrected to available option)"

    return result


async def llm_batch_decisions(
    agents_products: list[tuple],
    api_key: str,
    model: str = DEFAULT_MODEL,
    api_url: str = DEFAULT_API_URL,
) -> list[dict]:
    """Process multiple agent purchase decisions concurrently.

    Args:
        agents_products: List of (agent_profile_dict, product_dict, protocols_list) tuples.
        api_key: OpenCode API key.
        model: Model identifier.
        api_url: API endpoint URL.

    Returns:
        List of decision dicts, one per input tuple. Failed decisions return
        {"buy": False, "protocol": "", "reasoning": "LLM error: ..."}.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _limited(agent_profile, product, protocols):
        async with semaphore:
            try:
                return await llm_purchase_decision(
                    agent_profile, product, protocols,
                    api_key=api_key, model=model, api_url=api_url,
                )
            except Exception as e:
                logger.warning("LLM decision failed: %s", e)
                return {"buy": False, "protocol": "", "reasoning": f"LLM error: {e}"}

    tasks = [
        _limited(agent_prof, prod, protos)
        for agent_prof, prod, protos in agents_products
    ]
    return await asyncio.gather(*tasks)


class LLMDecisionEngine:
    """Stateful wrapper around LLM purchase decisions with usage tracking and fallback."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        api_url: str = DEFAULT_API_URL,
    ):
        self.api_key = api_key
        self.model = model
        self.api_url = api_url
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_requests = 0
        self.failed_requests = 0
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    def _agent_to_dict(self, agent) -> dict:
        """Convert an AgentProfile to the dict format expected by the prompt builder."""
        return {
            "name": agent.name,
            "budget": agent.budget,
            "remaining_budget": agent.remaining_budget,
            "price_sensitivity": agent.price_sensitivity,
            "brand_loyalty": agent.brand_loyalty,
            "preferred_categories": agent.preferred_categories,
        }

    async def decide(
        self,
        agent,
        product: dict,
        protocols: list[str],
        rng=None,
    ) -> dict:
        """Make an LLM-powered decision, falling back to rule-based on error.

        Args:
            agent: AgentProfile instance.
            product: Product dict with name, base_price, category, description.
            protocols: List of protocol name strings.
            rng: Random instance for rule-based fallback.

        Returns:
            {"buy": bool, "protocol": str, "reasoning": str}
        """
        agent_dict = self._agent_to_dict(agent)
        product_dict = {
            "name": product.get("name", "Unknown"),
            "price": product.get("base_price", product.get("price", 0)),
            "category": product.get("category", ""),
            "description": product.get("description", ""),
        }
        protocol_strs = [p.value if hasattr(p, "value") else str(p) for p in protocols]

        async with self._semaphore:
            try:
                self.total_requests += 1

                key = self.api_key
                system_prompt = _build_system_prompt(agent_dict, protocol_strs)
                user_prompt = _build_user_prompt(product_dict)

                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 256,
                }
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                }

                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(self.api_url, json=payload, headers=headers) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            raise ValueError(f"API {resp.status}: {body[:300]}")
                        data = await resp.json()

                # Track token usage
                usage = data.get("usage", {})
                self.total_prompt_tokens += usage.get("prompt_tokens", 0)
                self.total_completion_tokens += usage.get("completion_tokens", 0)

                result = _parse_llm_response(data)

                # Validate protocol
                if result["protocol"] not in protocol_strs:
                    result["protocol"] = protocol_strs[0] if protocol_strs else ""
                    result["reasoning"] += " (protocol corrected)"

                return result

            except Exception as e:
                self.failed_requests += 1
                logger.warning("LLM decision failed for %s, falling back to rules: %s", agent.name, e)
                return self._fallback_decision(agent, product, protocols, rng)

    def _fallback_decision(self, agent, product: dict, protocols: list, rng) -> dict:
        """Rule-based fallback matching AgentProfile.wants_to_buy() logic."""
        import random as stdlib_random

        if rng is None:
            rng = stdlib_random

        price = product.get("base_price", product.get("price", 0))
        category = product.get("category", "")
        buy = agent.wants_to_buy(price, category, rng)

        protocol_strs = [p.value if hasattr(p, "value") else str(p) for p in protocols]
        protocol = protocol_strs[0] if protocol_strs else ""
        if buy and protocols:
            protocol = agent.pick_protocol(price, protocols, rng)

        return {
            "buy": buy,
            "protocol": protocol,
            "reasoning": "Rule-based fallback decision",
        }

    def usage_summary(self) -> dict:
        """Return a summary of API usage."""
        return {
            "total_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
        }
