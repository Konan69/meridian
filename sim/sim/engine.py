"""Meridian simulation engine — orchestrates an agent-driven stablecoin economy."""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from .agents import generate_agents
from .commerce import CommerceClient
from .economy import StablecoinEconomy
from .memory import MemoryUpdater
from .types import (
    BalanceDomain,
    DOMAIN_LABELS,
    PROTOCOL_FIXED_COST_CENTS,
    PROTOCOL_PREFERRED_WORKLOADS,
    PROTOCOL_PRIMITIVE_SUPPORT,
    PROTOCOL_TRAITS,
    AgentMemoryEvent,
    AgentProfile,
    AgentRole,
    EconomyWorldEvent,
    MerchantProfile,
    Protocol,
    ProtocolEcosystemState,
    RoundSummary,
    SimulationConfig,
    SimulationResult,
    TransactionRecord,
    WorkloadType,
)

if TYPE_CHECKING:
    from .graph import CommerceGraphBuilder
    from .llm import LLMDecisionEngine


class SimulationEngine:
    """Runs an agent economy simulation constrained by live payment protocols."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.client = CommerceClient(config.engine_url)
        self.agents: list[AgentProfile] = []
        self.products: list[dict] = []
        self.merchants: list[MerchantProfile] = []
        self.result = SimulationResult(config=config)
        self.rng = random.Random(config.seed)
        self.llm_engine: Optional["LLMDecisionEngine"] = None
        self.graph: Optional["CommerceGraphBuilder"] = None
        self.memory: Optional[MemoryUpdater] = None
        self.economy: Optional[StablecoinEconomy] = None
        world_hash = sum((idx + 1) * ord(ch) for idx, ch in enumerate(config.world_seed))
        self.world_id = f"world_{config.seed}_{world_hash % 1_000_000:06d}"
        self.agent_memory_log: list[AgentMemoryEvent] = []
        self.world_events: list[EconomyWorldEvent] = []
        self.active_protocols: list[Protocol] = list(self.config.protocols)
        self.protocol_state: dict[str, ProtocolEcosystemState] = {
            proto.value: ProtocolEcosystemState(
                protocol=proto,
                observed_settlement_ms=PROTOCOL_TRAITS[proto]["settlement_ms"],
                reliability=0.99 if proto == Protocol.X402 else 0.96,
            )
            for proto in self.active_protocols
        }

        if config.use_llm:
            api_key = os.environ.get("OPENCODE_API_KEY", "")
            if api_key:
                from .llm import LLMDecisionEngine

                self.llm_engine = LLMDecisionEngine(
                    api_key=api_key,
                    model=config.llm_model,
                )
                self._emit("llm_enabled", {"model": config.llm_model})
            else:
                raise RuntimeError("MERIDIAN_USE_LLM is enabled but OPENCODE_API_KEY is not set")

    def _emit(self, event_type: str, data: dict):
        payload = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        print(json.dumps(payload), flush=True)

    def _record_world_event(
        self,
        summary: RoundSummary | None,
        round_num: int,
        event_type: str,
        text: str,
        *,
        actor_id: str | None = None,
        protocol: Protocol | str | None = None,
        data: dict | None = None,
    ):
        protocol_value = protocol.value if isinstance(protocol, Protocol) else protocol
        event = EconomyWorldEvent(
            round_num=round_num,
            event_type=event_type,
            summary=text,
            actor_id=actor_id,
            protocol=protocol_value,
            data=data or {},
        )
        self.world_events.append(event)
        if summary is not None:
            summary.world_events.append(event)
        self._emit(
            "world_event",
            {
                "world_id": self.world_id,
                "round": round_num,
                "event_type": event_type,
                "summary": text,
                "actor_id": actor_id,
                "protocol": protocol_value,
                "data": data or {},
            },
        )

    def _protocol_trust_summary(self) -> dict[str, dict[str, float]]:
        summary: dict[str, dict[str, float]] = {}
        for protocol in self.active_protocols:
            values = [
                agent.protocol_trust.get(protocol.value, 0.6)
                for agent in self.agents
            ]
            if not values:
                summary[protocol.value] = {"avg": 0.0, "min": 0.0, "max": 0.0}
                continue
            summary[protocol.value] = {
                "avg": round(sum(values) / len(values), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
            }
        return summary

    def _apply_protocol_experience(
        self,
        agent: AgentProfile,
        protocol: Protocol,
        *,
        success: bool,
        ecosystem_pressure: float,
    ) -> tuple[float, float, float]:
        before = agent.protocol_trust.get(protocol.value, 0.6)
        state = self.protocol_state.get(protocol.value)
        reliability = state.reliability if state else 0.96
        network_effect = state.network_effect if state else 0.0
        social_boost = (
            (network_effect - 0.45)
            * agent.social_influence
            * self.config.social_memory_strength
            * 0.06
        )
        if success:
            delta = (
                0.035
                + reliability * 0.018
                + max(0.0, 1.0 - ecosystem_pressure) * 0.012
                + social_boost
            )
        else:
            delta = -(
                0.08
                + ecosystem_pressure * 0.04
                + (1.0 - agent.risk_tolerance) * 0.025
                - min(social_boost, 0.02)
            )
        delta *= self.config.market_learning_rate
        after = max(0.05, min(1.0, before + delta))
        agent.protocol_trust[protocol.value] = after
        return before, after, after - before

    def _classify_trust_driver(
        self,
        *,
        protocol: Protocol,
        success: bool,
        ecosystem_pressure: float,
        merchant: MerchantProfile | None,
    ) -> str:
        state = self.protocol_state.get(protocol.value)
        reliability = state.reliability if state else 0.96
        if not success:
            if ecosystem_pressure >= 0.5:
                return "failed_under_route_pressure"
            if reliability < 0.85:
                return "failed_low_protocol_reliability"
            return "failed_payment_error"

        if ecosystem_pressure >= 0.5:
            return "settled_despite_route_pressure"
        if merchant and merchant.reputation >= 0.8:
            return "settled_with_reputable_merchant"
        if reliability >= 0.98:
            return "settled_on_reliable_protocol"
        return "settled_payment"

    def _record_agent_memory(
        self,
        summary: RoundSummary,
        *,
        round_num: int,
        agent: AgentProfile,
        protocol: Protocol,
        workload_type: WorkloadType,
        sentiment_delta: float,
        trust_before: float,
        trust_after: float,
        amount_cents: int,
        merchant: MerchantProfile | None,
        product_name: str | None,
        route_id: str | None,
        reason: str,
        success: bool | None = None,
        ecosystem_pressure: float = 0.0,
    ):
        success = sentiment_delta >= 0 if success is None else success
        event = AgentMemoryEvent(
            round_num=round_num,
            agent_id=agent.agent_id,
            agent_name=agent.name,
            event_type="protocol_experience",
            protocol=protocol.value,
            workload_type=workload_type.value,
            sentiment_delta=round(sentiment_delta, 4),
            trust_before=round(trust_before, 4),
            trust_after=round(trust_after, 4),
            outcome="success" if success else "failure",
            trust_driver=self._classify_trust_driver(
                protocol=protocol,
                success=success,
                ecosystem_pressure=ecosystem_pressure,
                merchant=merchant,
            ),
            ecosystem_pressure=round(ecosystem_pressure, 4),
            amount_cents=amount_cents,
            merchant_id=merchant.merchant_id if merchant else None,
            merchant_name=merchant.name if merchant else None,
            merchant_reputation=round(merchant.reputation, 4) if merchant else None,
            product_name=product_name,
            route_id=route_id,
            reason=reason,
        )
        self.agent_memory_log.append(event)
        summary.agent_memories.append(event)
        self._emit(
            "agent_memory",
            {
                "world_id": self.world_id,
                "round": round_num,
                **asdict(event),
            },
        )

    async def setup(self):
        healthy = await self.client.health()
        if not healthy:
            self._emit(
                "error",
                {"message": f"Engine not reachable at {self.config.engine_url}"},
            )
            raise RuntimeError(f"Engine not reachable at {self.config.engine_url}")

        capabilities = await self.client.get_capabilities()
        supported = {
            Protocol(protocol)
            for protocol in capabilities.get("supported_protocols", [])
            if protocol in {p.value for p in Protocol}
        }
        self.active_protocols = [
            protocol for protocol in self.config.protocols if protocol in supported
        ]
        if not self.active_protocols:
            raise RuntimeError("No directly integrated protocols are available from the engine")
        self.config.protocols = list(self.active_protocols)
        self.protocol_state = {
            proto.value: ProtocolEcosystemState(
                protocol=proto,
                observed_settlement_ms=PROTOCOL_TRAITS[proto]["settlement_ms"],
                reliability=0.99 if proto == Protocol.X402 else 0.96,
            )
            for proto in self.active_protocols
        }

        self.products = await self.client.get_products()
        self.agents = generate_agents(
            num_agents=self.config.num_agents,
            budget_range=self.config.agent_budget_range,
            seed=self.config.seed,
        )
        self.merchants = self._build_merchants()
        self.economy = StablecoinEconomy(
            agents=self.agents,
            merchants=self.merchants,
            protocols=self.active_protocols,
            rng=self.rng,
        )
        self._refresh_protocol_market_state()

        self._emit(
            "setup",
            {
                "world_id": self.world_id,
                "world_seed": self.config.world_seed,
                "scenario_prompt": self.config.scenario_prompt,
                "products": len(self.products),
                "agents": len(self.agents),
                "merchants": len(self.merchants),
                "engine_url": self.config.engine_url,
                "supported_protocols": [proto.value for proto in self.active_protocols],
                "stable_universe": self.config.stable_universe,
            },
        )
        self._record_world_event(
            None,
            0,
            "world_seeded",
            "Seeded protocol economy with agents, merchants, stablecoin domains, and payment rails.",
            data={
                "world_seed": self.config.world_seed,
                "scenario_prompt": self.config.scenario_prompt,
                "agents": len(self.agents),
                "merchants": len(self.merchants),
                "protocols": [proto.value for proto in self.active_protocols],
            },
        )

        if os.environ.get("MERIDIAN_ENABLE_GRAPH") == "1":
            api_key = os.environ.get("OPENCODE_GO_API_KEY") or os.environ.get("OPENCODE_API_KEY")
            if not api_key:
                raise RuntimeError("MERIDIAN_ENABLE_GRAPH=1 requires OPENCODE_GO_API_KEY or OPENCODE_API_KEY")
            try:
                from .graph import CommerceGraphBuilder

                self.graph = CommerceGraphBuilder()
                await self.graph.initialize()
                self.memory = MemoryUpdater(self.graph)
                self._emit("graph_enabled", {"db_path": self.graph.db_path})
            except Exception as exc:
                raise RuntimeError(f"Knowledge graph init failed: {exc}") from exc

    def _build_protocol_summaries(self) -> dict[str, dict]:
        summaries: dict[str, dict] = {}
        transactions = [
            tx
            for round_summary in self.result.rounds
            for tx in round_summary.transactions
        ]

        for protocol in self.active_protocols:
            protocol_txs = [tx for tx in transactions if tx.protocol == protocol.value]
            successful = [tx for tx in protocol_txs if tx.success]
            failed = [tx for tx in protocol_txs if not tx.success]
            settlement_values = [tx.settlement_ms for tx in successful]
            state = self.protocol_state.get(protocol.value)

            summaries[protocol.value] = {
                "protocol": protocol.value,
                "total_transactions": len(protocol_txs),
                "successful_transactions": len(successful),
                "failed_transactions": len(failed),
                "total_volume_cents": sum(tx.amount for tx in successful),
                "total_fees_cents": sum(tx.fee for tx in successful),
                "avg_settlement_ms": round(
                    sum(settlement_values) / len(settlement_values), 3
                )
                if settlement_values
                else round(state.observed_settlement_ms, 3) if state else 0.0,
                "avg_authorization_ms": 0.0,
                "micropayment_count": sum(1 for tx in successful if tx.amount < 100),
                "refund_count": 0,
            }

        return summaries

    def _settlement_domains_for_protocols(
        self, protocols: list[Protocol]
    ) -> list[BalanceDomain]:
        domains: set[BalanceDomain] = set()
        for protocol in protocols:
            if protocol == Protocol.X402:
                domains.update(
                    [
                        BalanceDomain.BASE_USDC,
                        BalanceDomain.SOLANA_USDC,
                        BalanceDomain.GATEWAY_UNIFIED_USDC,
                    ]
                )
            elif protocol == Protocol.MPP:
                domains.update(
                    [BalanceDomain.TEMPO_USD, BalanceDomain.STRIPE_INTERNAL_USD]
                )
            elif protocol == Protocol.ACP:
                domains.add(BalanceDomain.STRIPE_INTERNAL_USD)
            elif protocol in (Protocol.AP2, Protocol.ATXP):
                domains.update(
                    [
                        BalanceDomain.BASE_USDC,
                        BalanceDomain.SOLANA_USDC,
                        BalanceDomain.GATEWAY_UNIFIED_USDC,
                    ]
                )
        return list(domains)

    def _preferred_domain_for_protocols(self, protocols: list[Protocol]) -> BalanceDomain:
        if Protocol.X402 in protocols:
            return self.rng.choice(
                [
                    BalanceDomain.BASE_USDC,
                    BalanceDomain.SOLANA_USDC,
                    BalanceDomain.GATEWAY_UNIFIED_USDC,
                ]
            )
        if Protocol.MPP in protocols:
            return self.rng.choice(
                [BalanceDomain.TEMPO_USD, BalanceDomain.STRIPE_INTERNAL_USD]
            )
        if Protocol.ACP in protocols:
            return BalanceDomain.STRIPE_INTERNAL_USD
        return BalanceDomain.BASE_USDC

    def _build_merchants(self) -> list[MerchantProfile]:
        merchants: list[MerchantProfile] = []
        by_category: dict[str, list[dict]] = {}
        for product in self.products:
            by_category.setdefault(product.get("category", "general"), []).append(product)

        protocol_templates = [
            [Protocol.ACP, Protocol.AP2, Protocol.X402],
            [Protocol.MPP, Protocol.ATXP, Protocol.X402],
            [Protocol.ACP, Protocol.MPP, Protocol.ATXP],
            [Protocol.AP2, Protocol.MPP, Protocol.X402, Protocol.ATXP],
            list(self.active_protocols),
        ]

        merchant_idx = 0
        for category, products in by_category.items():
            for i in range(self.config.merchants_per_category):
                template = protocol_templates[(merchant_idx + i) % len(protocol_templates)]
                accepted = [p for p in template if p in self.active_protocols]
                accepted_domains = self._settlement_domains_for_protocols(accepted)
                preferred_domain = self._preferred_domain_for_protocols(accepted)
                working_capital = self.rng.randint(10_000, 120_000)
                merchants.append(
                    MerchantProfile(
                        merchant_id=f"merchant_{merchant_idx:03d}",
                        name=f"{category}_merchant_{i}",
                        category=category,
                        product_ids=[p["id"] for p in products],
                        accepted_protocols=accepted,
                        reputation=max(
                            0.35, min(0.95, 0.55 + self.rng.gauss(0, 0.12))
                        ),
                        scale_bias=max(
                            0.1, min(1.0, 0.5 + self.rng.gauss(0, 0.18))
                        ),
                        preferred_settlement_domain=preferred_domain,
                        accepted_settlement_domains=accepted_domains,
                        rebalance_threshold_cents=max(2_500, working_capital // 4),
                        rebalance_target_mix={
                            preferred_domain.value: 0.7,
                            **{
                                domain.value: round(
                                    0.3 / max(1, len(accepted_domains) - 1), 2
                                )
                                for domain in accepted_domains
                                if domain != preferred_domain
                            },
                        },
                        working_capital_cents=working_capital,
                    )
                )
                merchant_idx += 1
        return merchants

    def _refresh_protocol_market_state(self):
        for proto in self.protocol_state.values():
            proto.merchant_count = sum(
                1
                for merchant in self.merchants
                if proto.protocol in merchant.accepted_protocols
            )
            total_attempts = proto.attempted_transactions or 1
            if proto.attempted_transactions:
                proto.reliability = max(
                    0.55,
                    min(0.999, proto.successful_transactions / total_attempts),
                )
            proto.network_effect = min(
                1.0,
                (proto.merchant_count / max(1, len(self.merchants))) * 0.45
                + proto.reliability * 0.25
                + (
                    proto.gross_volume_cents
                    / max(1, self.result.total_volume or proto.gross_volume_cents or 1)
                )
                * 0.30,
            )

    def _choose_active_agents(self) -> list[AgentProfile]:
        eligible = [agent for agent in self.agents if agent.remaining_budget > 0]
        if not eligible:
            return []

        max_active = max(1, int(len(eligible) * self.config.max_active_ratio))
        count = self.rng.randint(max(1, max_active // 2), max_active)
        self.rng.shuffle(eligible)
        return eligible[:count]

    def _choose_workload(self, agent: AgentProfile) -> WorkloadType:
        weighted: dict[WorkloadType, float] = {
            WorkloadType.API_MICRO: self.config.flow_mix.get(WorkloadType.API_MICRO, 0.0),
            WorkloadType.CONSUMER_CHECKOUT: self.config.flow_mix.get(
                WorkloadType.CONSUMER_CHECKOUT, 0.0
            ),
        }
        if agent.risk_tolerance > 0.7 or agent.price_sensitivity > 0.7:
            weighted[WorkloadType.API_MICRO] += 0.12
        if agent.remaining_budget > max(15_000, agent.budget // 2) and agent.checkout_patience < 0.5:
            weighted[WorkloadType.CONSUMER_CHECKOUT] += 0.1

        total = sum(weighted.values())
        draw = self.rng.random() * total
        cursor = 0.0
        for workload, weight in weighted.items():
            cursor += weight
            if draw <= cursor:
                return workload
        return WorkloadType.CONSUMER_CHECKOUT

    def _pick_market_opportunity(
        self, agent: AgentProfile, workload_type: WorkloadType
    ) -> tuple[Optional[MerchantProfile], Optional[dict]]:
        category_filtered = [
            product
            for product in self.products
            if not agent.preferred_categories
            or product.get("category") in agent.preferred_categories
        ]
        product_pool = category_filtered or self.products

        if workload_type == WorkloadType.API_MICRO:
            micros = [
                product
                for product in product_pool
                if product.get("base_price", 0) <= 500 and not product.get("requires_shipping", False)
            ]
            product_pool = micros or product_pool
        elif workload_type == WorkloadType.CONSUMER_CHECKOUT:
            consumer = [
                product
                for product in product_pool
                if product.get("base_price", 0) >= 500
            ]
            product_pool = consumer or product_pool

        product = self.rng.choice(product_pool)
        merchants = [
            merchant
            for merchant in self.merchants
            if product["id"] in merchant.product_ids
            and any(proto in self.active_protocols for proto in merchant.accepted_protocols)
        ]
        if not merchants:
            return None, None

        merchant = max(
            merchants,
            key=lambda m: m.reputation * 0.55
            + len(m.accepted_protocols) * 0.12
            + m.scale_bias * 0.23
            + self.rng.random() * 0.1,
        )
        return merchant, product

    def _score_option(
        self,
        agent: AgentProfile,
        merchant: MerchantProfile,
        amount: int,
        workload_type: WorkloadType,
        option: dict,
    ) -> float:
        protocol = option["protocol"]
        route = option["route"]
        state = self.protocol_state[protocol.value]
        trust = agent.protocol_trust.get(protocol.value, 0.6)
        preference = 0.16 if agent.protocol_preference == protocol else 0.0
        merchant_fit = merchant.reputation * 0.18 + len(merchant.accepted_protocols) * 0.05
        fee_penalty = (
            option["estimated_protocol_fee_cents"] + option["route_fee_cents"]
        ) / max(amount, 1)
        latency_penalty = route.latency_ms / 3000.0
        congestion_penalty = max(0.0, option["capacity_ratio"] - 1.0) * (
            1.15 - agent.checkout_patience
        )
        domain_penalty = option["domain_mismatch"] * 0.12
        workload_bonus = 0.12 if workload_type in PROTOCOL_PREFERRED_WORKLOADS[protocol] else 0.0
        if workload_type == WorkloadType.API_MICRO and amount <= 100:
            workload_bonus += 0.15 if PROTOCOL_TRAITS[protocol]["supports_micropay"] else -0.2

        return (
            trust
            + preference
            + merchant_fit
            + state.reliability * 0.35
            + state.network_effect * 0.30
            + workload_bonus
            - fee_penalty * (0.85 + agent.price_sensitivity)
            - latency_penalty * (1.0 - agent.checkout_patience)
            - congestion_penalty
            - domain_penalty
        )

    def _choose_payment_option(
        self,
        agent: AgentProfile,
        merchant: MerchantProfile,
        amount: int,
        workload_type: WorkloadType,
        available_protocols: list[Protocol],
        target_domains: list[BalanceDomain],
    ) -> Optional[dict]:
        assert self.economy is not None
        options = self.economy.enumerate_payment_options(
            owner_kind=AgentRole.BUYER,
            owner_id=agent.agent_id,
            amount_cents=amount,
            workload_type=workload_type,
            target_domains=target_domains,
            available_protocols=available_protocols,
        )
        if not options:
            return None

        scored = [
            (option, self._score_option(agent, merchant, amount, workload_type, option))
            for option in options
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        best_option, best_score = scored[0]
        walkaway_threshold = -0.12 + agent.risk_tolerance * 0.1
        if best_score < walkaway_threshold:
            return None
        return best_option

    def _margin_delta(self, protocol: Protocol, route_fee: int, protocol_fee: int) -> int:
        infra_cost = int(route_fee * 0.55 + protocol_fee * 0.25 + PROTOCOL_FIXED_COST_CENTS[protocol] * 0.01)
        return protocol_fee - infra_cost

    def _record_protocol_economics(
        self,
        protocol: Protocol,
        amount: int,
        protocol_fee: int,
        settlement_ms: float,
        success: bool,
        ecosystem_pressure: float,
        route_id: str,
        route_fee: int,
    ) -> int:
        state = self.protocol_state[protocol.value]
        state.attempted_transactions += 1
        state.congestion = max(state.congestion, ecosystem_pressure)
        state.scale_pressure = max(state.scale_pressure, ecosystem_pressure)
        state.route_mix[route_id] = state.route_mix.get(route_id, 0) + 1
        margin_delta = self._margin_delta(protocol, route_fee, protocol_fee)

        if success:
            state.successful_transactions += 1
            state.gross_volume_cents += amount
            state.fee_revenue_cents += protocol_fee
            state.infrastructure_cost_cents += max(route_fee, int(protocol_fee * 0.35))
            state.operator_margin_cents += margin_delta
            state.observed_settlement_ms = state.observed_settlement_ms * 0.7 + settlement_ms * 0.3
        else:
            state.failed_transactions += 1
            state.infrastructure_cost_cents += max(route_fee // 2, 1)
            state.operator_margin_cents -= max(route_fee // 2, 1)
            state.observed_settlement_ms = (
                state.observed_settlement_ms * 0.8
                + PROTOCOL_TRAITS[protocol]["settlement_ms"] * (1.0 + ecosystem_pressure) * 0.2
            )
        return margin_delta

    async def _handle_buyer_flow(
        self,
        agent: AgentProfile,
        round_num: int,
        summary: RoundSummary,
    ):
        assert self.economy is not None

        workload_type = self._choose_workload(agent)
        merchant, product = self._pick_market_opportunity(agent, workload_type)
        if not merchant or not product:
            return

        price = product["base_price"]
        if not agent.wants_to_buy(price, product.get("category", ""), self.rng):
            return

        if self.llm_engine:
            decision = await self.llm_engine.decide(
                {
                    "name": agent.name,
                    "remaining_budget": agent.remaining_budget,
                    "price_sensitivity": agent.price_sensitivity,
                    "preferred_categories": agent.preferred_categories,
                    "budget": agent.budget,
                    "risk_tolerance": agent.risk_tolerance,
                },
                {
                    "name": product.get("name", ""),
                    "price": price,
                    "category": product.get("category", ""),
                },
                [proto.value for proto in merchant.accepted_protocols if proto in self.active_protocols],
                self.rng,
            )
            if not decision.get("buy", False):
                return

        option = self._choose_payment_option(
            agent=agent,
            merchant=merchant,
            amount=price,
            workload_type=workload_type,
            available_protocols=[p for p in merchant.accepted_protocols if p in self.active_protocols],
            target_domains=merchant.accepted_settlement_domains,
        )
        if option is None:
            return

        reservation = self.economy.reserve(
            owner_kind=AgentRole.BUYER,
            owner_id=agent.agent_id,
            option=option,
            amount_cents=price,
            workload_type=workload_type,
            round_num=round_num,
        )
        if reservation is None:
            return

        route = option["route"]
        summary.protocol_attempts[option["protocol"].value] = (
            summary.protocol_attempts.get(option["protocol"].value, 0) + 1
        )
        summary.route_usage[route.route_id] = summary.route_usage.get(route.route_id, 0) + 1

        if workload_type == WorkloadType.CONSUMER_CHECKOUT:
            record = await self.client.full_purchase(
                agent_id=agent.agent_id,
                product_id=product["id"],
                quantity=1,
                protocol=option["protocol"].value,
                round_num=round_num,
                product_name=product.get("name", ""),
                needs_shipping=product.get("requires_shipping", False),
                agent_address=agent.address if product.get("requires_shipping", False) else None,
                merchant_id=merchant.merchant_id,
                merchant_name=merchant.name,
                ecosystem_pressure=max(0.0, option["capacity_ratio"] - 1.0),
                workload_type=workload_type.value,
                source_domain=option["source_domain"].value,
                target_domain=option["target_domain"].value,
                primitive=route.primitive.value,
                route_id=route.route_id,
            )
        else:
            record = await self.client.execute_payment(
                actor_id=agent.agent_id,
                protocol=option["protocol"].value,
                amount_cents=price,
                merchant=merchant.merchant_id,
                round_num=round_num,
                workload_type=workload_type.value,
                source_domain=option["source_domain"].value,
                target_domain=option["target_domain"].value,
                primitive=route.primitive.value,
                route_id=route.route_id,
            )

        if record.success:
            route_record = self.economy.settle_success(
                reservation_id=reservation.reservation_id,
                target_owner_kind=AgentRole.MERCHANT,
                target_owner_id=merchant.merchant_id,
                target_domain=option["target_domain"],
                actual_protocol_fee_cents=record.fee,
                round_num=round_num,
            )
            margin_delta = self._record_protocol_economics(
                protocol=option["protocol"],
                amount=record.amount,
                protocol_fee=record.fee,
                settlement_ms=record.settlement_ms,
                success=True,
                ecosystem_pressure=max(0.0, option["capacity_ratio"] - 1.0),
                route_id=route.route_id,
                route_fee=route_record.route_fee_cents,
            )
            record.margin_delta_cents = margin_delta
            record.workload_type = workload_type.value
            record.source_domain = option["source_domain"].value
            record.target_domain = option["target_domain"].value
            record.primitive = route.primitive.value
            record.route_id = route.route_id
            ecosystem_pressure = max(0.0, option["capacity_ratio"] - 1.0)
            trust_before, trust_after, sentiment_delta = self._apply_protocol_experience(
                agent,
                option["protocol"],
                success=True,
                ecosystem_pressure=ecosystem_pressure,
            )
            agent.spent += record.amount
            merchant.reputation = min(0.99, merchant.reputation + 0.01)
            summary.transactions.append(record)
            summary.route_executions.append(route_record)
            self._record_agent_memory(
                summary,
                round_num=round_num,
                agent=agent,
                protocol=option["protocol"],
                workload_type=workload_type,
                sentiment_delta=sentiment_delta,
                trust_before=trust_before,
                trust_after=trust_after,
                amount_cents=record.amount,
                merchant=merchant,
                product_name=product["name"],
                route_id=route.route_id,
                reason="payment_settled",
                success=True,
                ecosystem_pressure=ecosystem_pressure,
            )
            summary.success_count += 1
            summary.total_volume += record.amount
            summary.total_fees += record.fee
            summary.merchant_sales[merchant.merchant_id] = summary.merchant_sales.get(merchant.merchant_id, 0) + 1

            self._emit(
                "purchase",
                {
                    "agent": agent.agent_id,
                    "merchant": merchant.name,
                    "merchant_id": merchant.merchant_id,
                    "product": product["name"],
                    "protocol": option["protocol"].value,
                    "amount_cents": record.amount,
                    "fee_cents": record.fee,
                    "settlement_ms": record.settlement_ms,
                    "source_domain": option["source_domain"].value,
                    "target_domain": option["target_domain"].value,
                    "primitive": route.primitive.value,
                    "route_id": route.route_id,
                    "ecosystem_pressure": ecosystem_pressure,
                    "margin_delta_cents": margin_delta,
                    "trust_before": round(trust_before, 4),
                    "trust_after": round(trust_after, 4),
                    "workload_type": workload_type.value,
                    "round": round_num,
                },
            )
            if self.memory:
                await self.memory.record_purchase(
                    agent_id=agent.agent_id,
                    product_name=product["name"],
                    protocol=option["protocol"].value,
                    amount_cents=record.amount,
                    round_num=round_num,
                )
        else:
            route_record = self.economy.settle_failure(
                reservation_id=reservation.reservation_id,
                reason=record.error or "payment_failed",
            )
            ecosystem_pressure = max(0.0, option["capacity_ratio"] - 1.0)
            self._record_protocol_economics(
                protocol=option["protocol"],
                amount=price,
                protocol_fee=0,
                settlement_ms=PROTOCOL_TRAITS[option["protocol"]]["settlement_ms"],
                success=False,
                ecosystem_pressure=ecosystem_pressure,
                route_id=route.route_id,
                route_fee=route_record.route_fee_cents,
            )
            trust_before, trust_after, sentiment_delta = self._apply_protocol_experience(
                agent,
                option["protocol"],
                success=False,
                ecosystem_pressure=ecosystem_pressure,
            )
            merchant.reputation = max(0.2, merchant.reputation - 0.015)
            summary.transactions.append(record)
            summary.route_executions.append(route_record)
            self._record_agent_memory(
                summary,
                round_num=round_num,
                agent=agent,
                protocol=option["protocol"],
                workload_type=workload_type,
                sentiment_delta=sentiment_delta,
                trust_before=trust_before,
                trust_after=trust_after,
                amount_cents=price,
                merchant=merchant,
                product_name=product["name"],
                route_id=route.route_id,
                reason=record.error or "payment_failed",
                success=False,
                ecosystem_pressure=ecosystem_pressure,
            )
            summary.fail_count += 1
            self._emit(
                "purchase_failed",
                {
                    "agent": agent.agent_id,
                    "merchant": merchant.merchant_id,
                    "protocol": option["protocol"].value,
                    "error": record.error,
                    "source_domain": option["source_domain"].value,
                    "target_domain": option["target_domain"].value,
                    "primitive": route.primitive.value,
                    "route_id": route.route_id,
                    "workload_type": workload_type.value,
                    "ecosystem_pressure": ecosystem_pressure,
                    "trust_before": round(trust_before, 4),
                    "trust_after": round(trust_after, 4),
                    "round": round_num,
                },
            )
            if self.memory:
                await self.memory.record_failure(
                    agent_id=agent.agent_id,
                    protocol=option["protocol"].value,
                    error=record.error or "unknown",
                    round_num=round_num,
                )

    async def _handle_rebalances(self, round_num: int, summary: RoundSummary):
        assert self.economy is not None
        for merchant in self.merchants:
            intent = self.economy.merchant_needs_rebalance(merchant)
            if not intent:
                continue

            options = self.economy.enumerate_payment_options(
                owner_kind=AgentRole.MERCHANT,
                owner_id=merchant.merchant_id,
                amount_cents=intent["amount_cents"],
                workload_type=WorkloadType.TREASURY_REBALANCE,
                target_domains=[intent["target_domain"]],
                available_protocols=[p for p in merchant.accepted_protocols if p in self.active_protocols],
            )
            if not options:
                continue

            option = max(
                options,
                key=lambda candidate: (
                    self.protocol_state[candidate["protocol"].value].reliability,
                    -candidate["route_fee_cents"],
                    -candidate["estimated_protocol_fee_cents"],
                ),
            )
            reservation = self.economy.reserve(
                owner_kind=AgentRole.MERCHANT,
                owner_id=merchant.merchant_id,
                option=option,
                amount_cents=intent["amount_cents"],
                workload_type=WorkloadType.TREASURY_REBALANCE,
                round_num=round_num,
            )
            if reservation is None:
                continue

            route = option["route"]
            record = await self.client.execute_payment(
                actor_id=merchant.merchant_id,
                protocol=option["protocol"].value,
                amount_cents=intent["amount_cents"],
                merchant=f"treasury_rebalance:{merchant.merchant_id}:{intent['target_domain'].value}",
                round_num=round_num,
                workload_type=WorkloadType.TREASURY_REBALANCE.value,
                source_domain=option["source_domain"].value,
                target_domain=intent["target_domain"].value,
                primitive=route.primitive.value,
                route_id=route.route_id,
            )

            if record.success:
                route_record = self.economy.settle_success(
                    reservation_id=reservation.reservation_id,
                    target_owner_kind=AgentRole.MERCHANT,
                    target_owner_id=merchant.merchant_id,
                    target_domain=intent["target_domain"],
                    actual_protocol_fee_cents=record.fee,
                    round_num=round_num,
                )
                margin_delta = self._record_protocol_economics(
                    protocol=option["protocol"],
                    amount=intent["amount_cents"],
                    protocol_fee=record.fee,
                    settlement_ms=record.settlement_ms,
                    success=True,
                    ecosystem_pressure=max(0.0, option["capacity_ratio"] - 1.0),
                    route_id=route.route_id,
                    route_fee=route_record.route_fee_cents,
                )
                record.margin_delta_cents = margin_delta
                record.source_domain = option["source_domain"].value
                record.target_domain = intent["target_domain"].value
                record.primitive = route.primitive.value
                record.route_id = route.route_id
                summary.transactions.append(record)
                summary.route_executions.append(route_record)
                summary.success_count += 1
                summary.total_volume += record.amount
                summary.total_fees += record.fee
                self._emit(
                    "treasury_rebalance",
                    {
                        "merchant_id": merchant.merchant_id,
                        "merchant": merchant.name,
                        "protocol": option["protocol"].value,
                        "amount_cents": record.amount,
                        "fee_cents": record.fee,
                        "source_domain": option["source_domain"].value,
                        "target_domain": intent["target_domain"].value,
                        "primitive": route.primitive.value,
                        "route_id": route.route_id,
                        "round": round_num,
                    },
                )
            else:
                route_record = self.economy.settle_failure(
                    reservation_id=reservation.reservation_id,
                    reason=record.error or "rebalance_failed",
                )
                summary.transactions.append(record)
                summary.route_executions.append(route_record)
                summary.fail_count += 1

    def _evolve_market(self, round_num: int, summary: RoundSummary):
        ranked = sorted(
            self.protocol_state.values(),
            key=lambda state: (
                state.operator_margin_cents,
                state.reliability,
                state.network_effect,
            ),
            reverse=True,
        )
        top_two = {state.protocol for state in ranked[:2]}
        switches: list[dict] = []

        for merchant in self.merchants:
            if self.rng.random() < 0.12:
                best_missing = [
                    protocol
                    for protocol in top_two
                    if protocol not in merchant.accepted_protocols
                ]
                if best_missing:
                    merchant.accepted_protocols.append(best_missing[0])
                    switches.append(
                        {
                            "merchant_id": merchant.merchant_id,
                            "merchant": merchant.name,
                            "action": "adopted",
                            "protocol": best_missing[0].value,
                            "round": round_num,
                        }
                    )
            if self.rng.random() < 0.06 and len(merchant.accepted_protocols) > 2:
                worst = min(
                    merchant.accepted_protocols,
                    key=lambda protocol: self.protocol_state[protocol.value].operator_margin_cents,
                )
                merchant.accepted_protocols.remove(worst)
                switches.append(
                    {
                        "merchant_id": merchant.merchant_id,
                        "merchant": merchant.name,
                        "action": "removed",
                        "protocol": worst.value,
                        "round": round_num,
                    }
                )

        self._refresh_protocol_market_state()
        for switch in switches:
            self._emit("merchant_switch", switch)
            self._record_world_event(
                summary,
                round_num,
                "merchant_protocol_mix_changed",
                f"{switch['merchant']} {switch['action']} {switch['protocol'].upper()} after observing rail economics.",
                actor_id=switch["merchant_id"],
                protocol=switch["protocol"],
                data=switch,
            )

        trust_shifts: list[dict] = []
        for agent in self.agents:
            if self.rng.random() > 0.08 * self.config.social_memory_strength:
                continue
            ranked_trust = sorted(
                agent.protocol_trust.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            if not ranked_trust:
                continue
            best_protocol, best_trust = ranked_trust[0]
            current = agent.protocol_preference.value if agent.protocol_preference else None
            current_trust = agent.protocol_trust.get(current, 0.6) if current else 0.6
            if best_protocol != current and best_trust - current_trust > 0.08:
                agent.protocol_preference = Protocol(best_protocol)
                shift = {
                    "agent_id": agent.agent_id,
                    "agent": agent.name,
                    "protocol": best_protocol,
                    "trust": round(best_trust, 4),
                    "round": round_num,
                }
                trust_shifts.append(shift)

        for shift in trust_shifts:
            self._emit("agent_preference_shift", shift)
            self._record_world_event(
                summary,
                round_num,
                "agent_preference_shift",
                f"{shift['agent']} now prefers {shift['protocol'].upper()} after accumulated payment memories.",
                actor_id=shift["agent_id"],
                protocol=shift["protocol"],
                data=shift,
            )

    async def run_round(self, round_num: int) -> RoundSummary:
        assert self.economy is not None
        self.economy.start_round(round_num)

        summary = RoundSummary(round_num=round_num)
        active_agents = self._choose_active_agents()
        summary.active_agents = len(active_agents)

        for agent in active_agents:
            await self._handle_buyer_flow(agent, round_num, summary)

        await self._handle_rebalances(round_num, summary)

        self._refresh_protocol_market_state()
        summary.ecosystem = {
            protocol: ProtocolEcosystemState(**state.__dict__)
            for protocol, state in self.protocol_state.items()
        }
        summary.route_usage = dict(self.economy.round_route_usage)
        summary.balance_summary = self.economy.snapshot_float_summary()
        summary.treasury_distribution = self.economy.snapshot_treasury_distribution()

        for event in self.economy.route_events:
            self._emit(event["type"], {k: v.value if hasattr(v, "value") else v for k, v in event.items() if k != "type"})
        for event in self.economy.balance_events:
            self._emit(event["type"], event | {"domain_label": DOMAIN_LABELS[BalanceDomain(event["domain"])]})

        for protocol_name, state in self.protocol_state.items():
            self.result.rail_pnl_history.setdefault(protocol_name, []).append(
                state.operator_margin_cents
            )
            self._emit(
                "rail_pnl_update",
                {
                    "protocol": protocol_name,
                    "operator_margin_cents": state.operator_margin_cents,
                    "fee_revenue_cents": state.fee_revenue_cents,
                    "infrastructure_cost_cents": state.infrastructure_cost_cents,
                    "round": round_num,
                },
            )
            self._emit(
                "market_snapshot",
                {
                    "protocol": protocol_name,
                    "merchant_count": state.merchant_count,
                    "network_effect": round(state.network_effect, 3),
                    "congestion": round(state.congestion, 3),
                    "reliability": round(state.reliability, 4),
                    "route_mix": state.route_mix,
                    "round": round_num,
                },
            )

        trust_summary = self._protocol_trust_summary()
        self._emit(
            "trust_snapshot",
            {
                "world_id": self.world_id,
                "round": round_num,
                "trust_summary": trust_summary,
            },
        )
        self._record_world_event(
            summary,
            round_num,
            "round_closed",
            f"Round {round_num} closed with {summary.success_count} settled transactions and {summary.fail_count} failures.",
            data={
                "active_agents": summary.active_agents,
                "success_count": summary.success_count,
                "fail_count": summary.fail_count,
                "volume_cents": summary.total_volume,
                "fees_cents": summary.total_fees,
                "trust_summary": trust_summary,
            },
        )

        self._emit(
            "round_complete",
            {
                "round": round_num,
                "active_agents": summary.active_agents,
                "success": summary.success_count,
                "failed": summary.fail_count,
                "volume_cents": summary.total_volume,
                "fees_cents": summary.total_fees,
                "protocol_attempts": summary.protocol_attempts,
                "route_usage": summary.route_usage,
                "memory_events": len(summary.agent_memories),
                "trust_summary": trust_summary,
            },
        )

        if self.graph:
            try:
                await self.graph.record_round(
                    {
                        "round_num": round_num,
                        "total_volume": summary.total_volume,
                        "total_fees": summary.total_fees,
                        "success_count": summary.success_count,
                        "fail_count": summary.fail_count,
                        "active_agents": summary.active_agents,
                    }
                )
            except Exception:
                pass

        if self.memory:
            for protocol, state in self.protocol_state.items():
                try:
                    await self.memory.record_market_snapshot(
                        protocol=protocol,
                        round_num=round_num,
                        merchant_count=state.merchant_count,
                        volume_cents=state.gross_volume_cents,
                        margin_cents=state.operator_margin_cents,
                        reliability=state.reliability,
                        congestion=state.congestion,
                    )
                except Exception:
                    pass

        self._evolve_market(round_num, summary)
        return summary

    async def run(self) -> SimulationResult:
        start_time = time.time()
        await self.setup()
        assert self.economy is not None

        self._emit(
            "simulation_start",
            {
                "world_id": self.world_id,
                "world_seed": self.config.world_seed,
                "scenario_prompt": self.config.scenario_prompt,
                "agents": self.config.num_agents,
                "rounds": self.config.num_rounds,
                "merchants": len(self.merchants),
                "protocols": [p.value for p in self.active_protocols],
                "flow_mix": {k.value: v for k, v in self.config.flow_mix.items()},
                "stable_universe": self.config.stable_universe,
            },
        )

        for round_num in range(1, self.config.num_rounds + 1):
            summary = await self.run_round(round_num)
            self.result.rounds.append(summary)
            self.result.total_transactions += summary.success_count + summary.fail_count
            self.result.total_volume += summary.total_volume

        self.result.duration_seconds = time.time() - start_time
        self.result.protocol_summaries = self._build_protocol_summaries()
        self.result.ecosystem_summary = {
            protocol: ProtocolEcosystemState(**state.__dict__)
            for protocol, state in self.protocol_state.items()
        }
        self.result.route_usage_summary = dict(self.economy.total_route_usage)
        self.result.float_summary = self.economy.snapshot_float_summary()
        self.result.treasury_distribution = self.economy.snapshot_treasury_distribution()
        self.result.trust_summary = self._protocol_trust_summary()
        self.result.agent_memory_log = list(self.agent_memory_log)
        self.result.world_events = list(self.world_events)

        completion_data = {
            "world_id": self.world_id,
            "simulation_world": {
                "world_id": self.world_id,
                "world_seed": self.config.world_seed,
                "scenario_prompt": self.config.scenario_prompt,
                "stable_universe": self.config.stable_universe,
                "agents": len(self.agents),
                "merchants": len(self.merchants),
                "protocols": [protocol.value for protocol in self.active_protocols],
                "memory_events": len(self.result.agent_memory_log),
                "world_events": len(self.result.world_events),
            },
            "total_transactions": self.result.total_transactions,
            "total_volume_cents": self.result.total_volume,
            "duration_seconds": round(self.result.duration_seconds, 2),
            "protocol_summaries": self.result.protocol_summaries,
            "ecosystem_summary": {
                protocol: {
                    "merchant_count": state.merchant_count,
                    "network_effect": round(state.network_effect, 3),
                    "congestion": round(state.congestion, 3),
                    "operator_margin_cents": state.operator_margin_cents,
                    "reliability": round(state.reliability, 4),
                    "route_mix": state.route_mix,
                }
                for protocol, state in self.result.ecosystem_summary.items()
            },
            "route_usage_summary": self.result.route_usage_summary,
            "float_summary": self.result.float_summary,
            "treasury_distribution": self.result.treasury_distribution,
            "rail_pnl_history": self.result.rail_pnl_history,
            "balances": self.economy.snapshot_balances(),
            "trust_summary": self.result.trust_summary,
            "agent_memory_log": [asdict(event) for event in self.result.agent_memory_log[-500:]],
            "world_events": [asdict(event) for event in self.result.world_events[-300:]],
        }
        if self.llm_engine:
            completion_data["llm_usage"] = self.llm_engine.usage_summary()
        self._emit("simulation_complete", completion_data)

        if self.memory:
            try:
                await self.memory.close()
            except Exception:
                pass
        if self.graph:
            try:
                await self.graph.close()
            except Exception:
                pass

        await self.client.close()
        return self.result

    def print_report(self, file=sys.stderr):
        r = self.result
        p = lambda *args, **kw: print(*args, **kw, file=file)
        p("\n" + "=" * 78)
        p("  MERIDIAN STABLECOIN ECONOMY REPORT")
        p("=" * 78)
        p(
            f"  Agents: {self.config.num_agents} | Merchants: {len(self.merchants)} | Rounds: {self.config.num_rounds} | Duration: {r.duration_seconds:.1f}s"
        )
        p(
            f"  Total Transactions: {r.total_transactions} | Volume: ${r.total_volume / 100:.2f}"
        )
        p()
        p(
            f"  {'Protocol':<8} {'Txns':>6} {'Volume':>12} {'Fees':>10} {'Margin':>10} {'NE':>6} {'CG':>6}"
        )
        p("  " + "-" * 82)
        proto_order = ["atxp", "x402", "mpp", "acp", "ap2"]
        active_names = [proto.value for proto in self.active_protocols]
        for proto_name in [name for name in proto_order if name in active_names]:
            pm = r.protocol_summaries.get(proto_name, {})
            eco = r.ecosystem_summary.get(proto_name)
            p(
                f"  {proto_name.upper():<8} {pm.get('total_transactions', 0):>6} "
                f"${pm.get('total_volume_cents', 0) / 100:>10.2f} "
                f"${pm.get('total_fees_cents', 0) / 100:>8.2f} "
                f"${(eco.operator_margin_cents if eco else 0) / 100:>8.2f} "
                f"{(eco.network_effect if eco else 0):>5.2f} {(eco.congestion if eco else 0):>5.2f}"
            )
        p("\n" + "=" * 78)


async def main():
    use_llm = os.environ.get("MERIDIAN_USE_LLM", "").lower() in ("1", "true", "yes")
    flow_mix_raw = os.environ.get("MERIDIAN_FLOW_MIX")
    protocols_raw = os.environ.get("MERIDIAN_PROTOCOLS")
    flow_mix = None
    if flow_mix_raw:
        flow_mix = json.loads(flow_mix_raw)
    configured_protocols = [Protocol.ACP, Protocol.X402, Protocol.AP2, Protocol.MPP, Protocol.ATXP]
    if protocols_raw:
        parsed_protocols = [
            Protocol(value.strip())
            for value in protocols_raw.split(",")
            if value.strip() in {protocol.value for protocol in Protocol}
        ]
        if parsed_protocols:
            configured_protocols = parsed_protocols

    config = SimulationConfig(
        num_agents=int(os.environ.get("MERIDIAN_AGENTS", "50")),
        num_rounds=int(os.environ.get("MERIDIAN_ROUNDS", "10")),
        protocols=configured_protocols,
        engine_url=os.environ.get("MERIDIAN_ENGINE_URL", "http://localhost:4080"),
        seed=int(os.environ.get("MERIDIAN_SEED", "42")),
        world_seed=os.environ.get("MERIDIAN_WORLD_SEED", "meridian-protocol-economy"),
        scenario_prompt=os.environ.get("MERIDIAN_SCENARIO_PROMPT", ""),
        use_llm=use_llm,
        llm_model=os.environ.get("MERIDIAN_LLM_MODEL", "minimax-m2.5"),
        merchants_per_category=int(os.environ.get("MERIDIAN_MERCHANTS_PER_CATEGORY", "3")),
        stable_universe=os.environ.get("MERIDIAN_STABLE_UNIVERSE", "usdc_centric"),
        market_learning_rate=float(os.environ.get("MERIDIAN_MARKET_LEARNING_RATE", "1.0")),
        social_memory_strength=float(os.environ.get("MERIDIAN_SOCIAL_MEMORY_STRENGTH", "0.35")),
        flow_mix=flow_mix
        or {
            WorkloadType.API_MICRO: 0.55,
            WorkloadType.CONSUMER_CHECKOUT: 0.30,
            WorkloadType.TREASURY_REBALANCE: 0.15,
        },
    )

    engine = SimulationEngine(config)
    await engine.run()
    engine.print_report()


if __name__ == "__main__":
    asyncio.run(main())
