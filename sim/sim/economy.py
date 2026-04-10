"""Stablecoin economy state and routing mechanics for Meridian."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import asdict
from typing import Optional

from .routes import ROUTE_MATRIX
from .types import (
    BalanceDomain,
    PROTOCOL_FEE_FORMULAS,
    PROTOCOL_PREFERRED_WORKLOADS,
    AgentProfile,
    AgentRole,
    MerchantProfile,
    Protocol,
    RouteExecutionRecord,
    RouteSpec,
    SettlementPrimitive,
    SettlementReservation,
    StableBalanceBucket,
    WorkloadType,
)


class StablecoinEconomy:
    """Tracks stablecoin balances, reservations, routes, and pending settlement."""

    def __init__(
        self,
        agents: list[AgentProfile],
        merchants: list[MerchantProfile],
        protocols: list[Protocol],
        rng,
    ):
        self.agents = agents
        self.merchants = merchants
        self.protocols = protocols
        self.rng = rng
        self.routes: dict[str, RouteSpec] = {route.route_id: route for route in ROUTE_MATRIX}
        self.buckets: dict[tuple[str, str, str], StableBalanceBucket] = {}
        self.reservations: dict[str, SettlementReservation] = {}
        self.pending_settlements: list[dict] = []
        self.round_route_usage: dict[str, int] = defaultdict(int)
        self.total_route_usage: dict[str, int] = defaultdict(int)
        self.balance_events: list[dict] = []
        self.route_events: list[dict] = []

        self._bootstrap_buckets()

    def _bucket_key(
        self, owner_kind: AgentRole, owner_id: str, domain: BalanceDomain
    ) -> tuple[str, str, str]:
        return (owner_kind.value, owner_id, domain.value)

    def _get_or_create_bucket(
        self,
        owner_kind: AgentRole,
        owner_id: str,
        domain: BalanceDomain,
        asset: str = "USDC",
    ) -> StableBalanceBucket:
        key = self._bucket_key(owner_kind, owner_id, domain)
        if key not in self.buckets:
            self.buckets[key] = StableBalanceBucket(
                owner_kind=owner_kind,
                owner_id=owner_id,
                domain=domain,
                asset=asset,
            )
        return self.buckets[key]

    def _bootstrap_buckets(self):
        buyer_domains = [
            BalanceDomain.BASE_USDC,
            BalanceDomain.SOLANA_USDC,
            BalanceDomain.TEMPO_USD,
        ]

        for agent in self.agents:
            num_domains = self.rng.randint(1, 3)
            chosen = self.rng.sample(buyer_domains, num_domains)
            remaining = agent.budget
            for idx, domain in enumerate(chosen):
                if idx == len(chosen) - 1:
                    alloc = remaining
                else:
                    alloc = int(remaining * max(0.15, min(0.65, self.rng.random())))
                    remaining -= alloc
                bucket = self._get_or_create_bucket(AgentRole.BUYER, agent.agent_id, domain)
                bucket.available_cents += alloc

        for merchant in self.merchants:
            working = merchant.working_capital_cents
            primary = int(working * 0.7)
            secondary_pool = working - primary
            primary_bucket = self._get_or_create_bucket(
                AgentRole.MERCHANT,
                merchant.merchant_id,
                merchant.preferred_settlement_domain,
            )
            primary_bucket.available_cents += primary
            remaining_domains = [
                domain
                for domain in merchant.accepted_settlement_domains
                if domain != merchant.preferred_settlement_domain
            ]
            if remaining_domains and secondary_pool > 0:
                share = secondary_pool // len(remaining_domains)
                for domain in remaining_domains:
                    bucket = self._get_or_create_bucket(
                        AgentRole.MERCHANT, merchant.merchant_id, domain
                    )
                    bucket.available_cents += share

        for protocol in self.protocols:
            domain = self.operator_fee_domain(protocol)
            self._get_or_create_bucket(AgentRole.OPERATOR, protocol.value, domain)

    def operator_fee_domain(self, protocol: Protocol) -> BalanceDomain:
        if protocol == Protocol.X402:
            return BalanceDomain.GATEWAY_UNIFIED_USDC
        if protocol in (Protocol.ACP, Protocol.MPP):
            return BalanceDomain.STRIPE_INTERNAL_USD
        if protocol == Protocol.AP2:
            return BalanceDomain.BASE_USDC
        return BalanceDomain.GATEWAY_UNIFIED_USDC

    def start_round(self, round_num: int):
        self.round_route_usage = defaultdict(int)
        self.balance_events = []
        self.route_events = []
        due = [p for p in self.pending_settlements if p["due_round"] <= round_num]
        self.pending_settlements = [
            p for p in self.pending_settlements if p["due_round"] > round_num
        ]
        for entry in due:
            bucket = self._get_or_create_bucket(
                entry["owner_kind"], entry["owner_id"], entry["domain"]
            )
            bucket.pending_in_cents -= entry["amount_cents"]
            bucket.available_cents += entry["amount_cents"]
            self.balance_events.append(
                {
                    "type": "balance_update",
                    "owner_kind": bucket.owner_kind.value,
                    "owner_id": bucket.owner_id,
                    "domain": bucket.domain.value,
                    "available_cents": bucket.available_cents,
                    "reserved_cents": bucket.reserved_cents,
                    "pending_in_cents": bucket.pending_in_cents,
                    "pending_out_cents": bucket.pending_out_cents,
                    "reason": "pending_settlement_cleared",
                }
            )

    def compute_route_fee(self, route: RouteSpec, amount_cents: int) -> int:
        return max((amount_cents * route.fee_bps) // 10_000 + route.fixed_fee_cents, route.fixed_fee_cents)

    def round_delay(self, latency_ms: int) -> int:
        if latency_ms >= 2000:
            return 2
        if latency_ms >= 900:
            return 1
        return 0

    def total_available(self, owner_kind: AgentRole, owner_id: str) -> int:
        return sum(
            bucket.available_cents
            for bucket in self.buckets.values()
            if bucket.owner_kind == owner_kind and bucket.owner_id == owner_id
        )

    def available_buckets(self, owner_kind: AgentRole, owner_id: str) -> list[StableBalanceBucket]:
        return [
            bucket
            for bucket in self.buckets.values()
            if bucket.owner_kind == owner_kind and bucket.owner_id == owner_id
        ]

    def enumerate_payment_options(
        self,
        owner_kind: AgentRole,
        owner_id: str,
        amount_cents: int,
        workload_type: WorkloadType,
        target_domains: list[BalanceDomain],
        available_protocols: list[Protocol],
    ) -> list[dict]:
        options: list[dict] = []
        for bucket in self.available_buckets(owner_kind, owner_id):
            if bucket.available_cents <= 0:
                continue
            for route in self.routes.values():
                if route.source_domain != bucket.domain:
                    continue
                if route.target_domain not in target_domains:
                    continue
                for protocol in available_protocols:
                    if protocol not in route.supported_protocols:
                        continue
                    if workload_type not in PROTOCOL_PREFERRED_WORKLOADS[protocol]:
                        continue
                    estimated_protocol_fee = PROTOCOL_FEE_FORMULAS[protocol](amount_cents)
                    route_fee = self.compute_route_fee(route, amount_cents)
                    total_required = amount_cents + estimated_protocol_fee + route_fee
                    if bucket.available_cents < total_required:
                        continue
                    projected_usage = self.round_route_usage[route.route_id] + amount_cents
                    capacity_ratio = projected_usage / max(1, route.capacity_cents_per_round)
                    options.append(
                        {
                            "protocol": protocol,
                            "route": route,
                            "source_domain": bucket.domain,
                            "target_domain": route.target_domain,
                            "estimated_protocol_fee_cents": estimated_protocol_fee,
                            "route_fee_cents": route_fee,
                            "total_required_cents": total_required,
                            "capacity_ratio": capacity_ratio,
                            "domain_mismatch": int(bucket.domain != route.target_domain),
                        }
                    )
        return options

    def reserve(
        self,
        owner_kind: AgentRole,
        owner_id: str,
        option: dict,
        amount_cents: int,
        workload_type: WorkloadType,
        round_num: int,
    ) -> Optional[SettlementReservation]:
        bucket = self._get_or_create_bucket(owner_kind, owner_id, option["source_domain"])
        total_required = option["total_required_cents"]
        if bucket.available_cents < total_required:
            return None

        bucket.available_cents -= total_required
        bucket.reserved_cents += total_required
        reservation = SettlementReservation(
            reservation_id=f"res_{uuid.uuid4().hex[:12]}",
            owner_kind=owner_kind,
            owner_id=owner_id,
            source_domain=option["source_domain"],
            amount_cents=amount_cents,
            reserved_total_cents=total_required,
            protocol=option["protocol"],
            workload_type=workload_type,
            route_id=option["route"].route_id,
            primitive=option["route"].primitive,
            round_num=round_num,
        )
        self.reservations[reservation.reservation_id] = reservation
        self.round_route_usage[reservation.route_id] += amount_cents
        self.total_route_usage[reservation.route_id] += amount_cents
        self.balance_events.append(
            {
                "type": "balance_update",
                "owner_kind": owner_kind.value,
                "owner_id": owner_id,
                "domain": bucket.domain.value,
                "available_cents": bucket.available_cents,
                "reserved_cents": bucket.reserved_cents,
                "pending_in_cents": bucket.pending_in_cents,
                "pending_out_cents": bucket.pending_out_cents,
                "reason": "reserved",
            }
        )
        return reservation

    def release_reservation(self, reservation_id: str, reason: str):
        reservation = self.reservations.pop(reservation_id, None)
        if reservation is None:
            return
        bucket = self._get_or_create_bucket(
            reservation.owner_kind, reservation.owner_id, reservation.source_domain
        )
        bucket.available_cents += reservation.reserved_total_cents
        bucket.reserved_cents -= reservation.reserved_total_cents
        self.balance_events.append(
            {
                "type": "balance_update",
                "owner_kind": bucket.owner_kind.value,
                "owner_id": bucket.owner_id,
                "domain": bucket.domain.value,
                "available_cents": bucket.available_cents,
                "reserved_cents": bucket.reserved_cents,
                "pending_in_cents": bucket.pending_in_cents,
                "pending_out_cents": bucket.pending_out_cents,
                "reason": reason,
            }
        )

    def settle_success(
        self,
        reservation_id: str,
        target_owner_kind: AgentRole,
        target_owner_id: str,
        target_domain: BalanceDomain,
        actual_protocol_fee_cents: int,
        round_num: int,
    ) -> RouteExecutionRecord:
        reservation = self.reservations.pop(reservation_id)
        source_bucket = self._get_or_create_bucket(
            reservation.owner_kind, reservation.owner_id, reservation.source_domain
        )
        route = self.routes[reservation.route_id]
        route_fee_cents = self.compute_route_fee(route, reservation.amount_cents)
        source_bucket.reserved_cents -= reservation.reserved_total_cents

        operator_bucket = self._get_or_create_bucket(
            AgentRole.OPERATOR, reservation.protocol.value, self.operator_fee_domain(reservation.protocol)
        )
        operator_bucket.available_cents += actual_protocol_fee_cents

        target_bucket = self._get_or_create_bucket(
            target_owner_kind,
            target_owner_id,
            target_domain,
        )

        delay = self.round_delay(route.latency_ms)
        if delay == 0:
            target_bucket.available_cents += reservation.amount_cents
            target_reason = "settled_immediately"
        else:
            target_bucket.pending_in_cents += reservation.amount_cents
            self.pending_settlements.append(
                {
                    "due_round": round_num + delay,
                    "owner_kind": target_owner_kind,
                    "owner_id": target_owner_id,
                    "domain": target_domain,
                    "amount_cents": reservation.amount_cents,
                }
            )
            target_reason = "pending_settlement"

        self.balance_events.extend(
            [
                {
                    "type": "balance_update",
                    "owner_kind": source_bucket.owner_kind.value,
                    "owner_id": source_bucket.owner_id,
                    "domain": source_bucket.domain.value,
                    "available_cents": source_bucket.available_cents,
                    "reserved_cents": source_bucket.reserved_cents,
                    "pending_in_cents": source_bucket.pending_in_cents,
                    "pending_out_cents": source_bucket.pending_out_cents,
                    "reason": "settled_source",
                },
                {
                    "type": "balance_update",
                    "owner_kind": target_bucket.owner_kind.value,
                    "owner_id": target_bucket.owner_id,
                    "domain": target_bucket.domain.value,
                    "available_cents": target_bucket.available_cents,
                    "reserved_cents": target_bucket.reserved_cents,
                    "pending_in_cents": target_bucket.pending_in_cents,
                    "pending_out_cents": target_bucket.pending_out_cents,
                    "reason": target_reason,
                },
                {
                    "type": "balance_update",
                    "owner_kind": operator_bucket.owner_kind.value,
                    "owner_id": operator_bucket.owner_id,
                    "domain": operator_bucket.domain.value,
                    "available_cents": operator_bucket.available_cents,
                    "reserved_cents": operator_bucket.reserved_cents,
                    "pending_in_cents": operator_bucket.pending_in_cents,
                    "pending_out_cents": operator_bucket.pending_out_cents,
                    "reason": "operator_fee_credit",
                },
            ]
        )

        record = RouteExecutionRecord(
            route_id=route.route_id,
            protocol=reservation.protocol,
            primitive=reservation.primitive,
            source_domain=reservation.source_domain,
            target_domain=target_domain,
            amount_cents=reservation.amount_cents,
            route_fee_cents=route_fee_cents,
            protocol_fee_cents=actual_protocol_fee_cents,
            latency_ms=route.latency_ms,
            success=True,
            workload_type=reservation.workload_type,
            reservation_id=reservation.reservation_id,
        )
        self.route_events.append({"type": "route_execution", **asdict(record)})
        return record

    def settle_failure(self, reservation_id: str, reason: str) -> RouteExecutionRecord:
        reservation = self.reservations[reservation_id]
        route = self.routes[reservation.route_id]
        record = RouteExecutionRecord(
            route_id=route.route_id,
            protocol=reservation.protocol,
            primitive=reservation.primitive,
            source_domain=reservation.source_domain,
            target_domain=route.target_domain,
            amount_cents=reservation.amount_cents,
            route_fee_cents=self.compute_route_fee(route, reservation.amount_cents),
            protocol_fee_cents=0,
            latency_ms=route.latency_ms,
            success=False,
            workload_type=reservation.workload_type,
            reservation_id=reservation.reservation_id,
            fail_reason=reason,
        )
        self.route_events.append({"type": "route_execution", **asdict(record)})
        self.release_reservation(reservation_id, "settlement_failed")
        return record

    def merchant_needs_rebalance(self, merchant: MerchantProfile) -> Optional[dict]:
        preferred_bucket = self._get_or_create_bucket(
            AgentRole.MERCHANT, merchant.merchant_id, merchant.preferred_settlement_domain
        )
        if preferred_bucket.available_cents >= merchant.working_capital_cents:
            return None

        candidates = [
            bucket
            for bucket in self.available_buckets(AgentRole.MERCHANT, merchant.merchant_id)
            if bucket.domain != merchant.preferred_settlement_domain
            and bucket.available_cents > merchant.rebalance_threshold_cents
        ]
        if not candidates:
            return None

        source_bucket = max(candidates, key=lambda bucket: bucket.available_cents)
        amount = min(
            source_bucket.available_cents // 2,
            merchant.rebalance_threshold_cents,
        )
        if amount <= 0:
            return None
        return {
            "source_domain": source_bucket.domain,
            "target_domain": merchant.preferred_settlement_domain,
            "amount_cents": amount,
        }

    def snapshot_float_summary(self) -> dict[str, int]:
        summary: dict[str, int] = defaultdict(int)
        for bucket in self.buckets.values():
            summary[bucket.domain.value] += (
                bucket.available_cents + bucket.pending_in_cents + bucket.reserved_cents
            )
        return dict(summary)

    def snapshot_treasury_distribution(self) -> dict[str, dict[str, int]]:
        distribution: dict[str, dict[str, int]] = {}
        for merchant in self.merchants:
            merchant_buckets = self.available_buckets(AgentRole.MERCHANT, merchant.merchant_id)
            distribution[merchant.merchant_id] = {
                bucket.domain.value: bucket.available_cents + bucket.pending_in_cents
                for bucket in merchant_buckets
                if bucket.available_cents + bucket.pending_in_cents > 0
            }
        return distribution

    def snapshot_balances(self) -> list[dict]:
        return [
            {
                "owner_kind": bucket.owner_kind.value,
                "owner_id": bucket.owner_id,
                "domain": bucket.domain.value,
                "available_cents": bucket.available_cents,
                "reserved_cents": bucket.reserved_cents,
                "pending_in_cents": bucket.pending_in_cents,
                "pending_out_cents": bucket.pending_out_cents,
            }
            for bucket in self.buckets.values()
            if (
                bucket.available_cents
                or bucket.reserved_cents
                or bucket.pending_in_cents
                or bucket.pending_out_cents
            )
        ]
