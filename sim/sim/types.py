"""Core types for the Meridian simulation layer."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import random


class Protocol(str, Enum):
    ACP = "acp"
    AP2 = "ap2"
    X402 = "x402"
    MPP = "mpp"
    ATXP = "atxp"


class AgentRole(str, Enum):
    BUYER = "buyer"
    MERCHANT = "merchant"


@dataclass
class AgentProfile:
    agent_id: str
    name: str
    role: AgentRole
    budget: int  # cents
    price_sensitivity: float  # 0.0 = doesn't care, 1.0 = extremely price sensitive
    brand_loyalty: float  # 0.0 = no loyalty, 1.0 = only buys from preferred
    preferred_categories: list[str] = field(default_factory=list)
    risk_tolerance: float = 0.5  # 0.0 = risk averse, 1.0 = risk seeking
    protocol_preference: Optional[Protocol] = None
    spent: int = 0  # cents spent so far

    @property
    def remaining_budget(self) -> int:
        return max(0, self.budget - self.spent)

    def wants_to_buy(self, price: int, category: str) -> bool:
        """Rule-based purchase decision. No LLM needed."""
        if price > self.remaining_budget:
            return False

        # Price sensitivity check
        if self.price_sensitivity > 0.7 and price > self.budget * 0.3:
            return random.random() > self.price_sensitivity

        # Category preference
        if self.preferred_categories and category not in self.preferred_categories:
            if random.random() < self.brand_loyalty:
                return False

        # Risk tolerance affects willingness to buy
        buy_probability = 0.5 + (self.risk_tolerance - 0.5) * 0.3
        return random.random() < buy_probability


@dataclass
class SimulationConfig:
    num_agents: int = 50
    num_rounds: int = 10
    protocols: list[Protocol] = field(
        default_factory=lambda: list(Protocol)
    )
    engine_url: str = "http://localhost:4080"
    seed: int = 42
    agent_budget_range: tuple[int, int] = (5000, 50000)  # $50 - $500 in cents


@dataclass
class TransactionRecord:
    round_num: int
    agent_id: str
    protocol: str
    product_id: str
    product_name: str
    amount: int  # cents
    fee: int  # cents
    settlement_ms: float
    success: bool
    session_id: Optional[str] = None
    order_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class RoundSummary:
    round_num: int
    transactions: list[TransactionRecord] = field(default_factory=list)
    total_volume: int = 0  # cents
    total_fees: int = 0  # cents
    success_count: int = 0
    fail_count: int = 0
    active_agents: int = 0


@dataclass
class SimulationResult:
    config: SimulationConfig
    rounds: list[RoundSummary] = field(default_factory=list)
    protocol_summaries: dict = field(default_factory=dict)
    total_transactions: int = 0
    total_volume: int = 0
    duration_seconds: float = 0.0
