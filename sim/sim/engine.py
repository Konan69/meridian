"""Meridian simulation engine — orchestrates agents across protocols."""

import asyncio
import json
import random
import sys
import time
from dataclasses import asdict
from typing import Optional

from .agents import generate_agents
from .commerce import CommerceClient
from .types import (
    AgentProfile,
    Protocol,
    RoundSummary,
    SimulationConfig,
    SimulationResult,
    TransactionRecord,
)


class SimulationEngine:
    """Runs multi-protocol commerce simulations with rule-based agents."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.client = CommerceClient(config.engine_url)
        self.agents: list[AgentProfile] = []
        self.products: list[dict] = []
        self.result = SimulationResult(config=config)
        self.rng = random.Random(config.seed)
        self._event_callback: Optional[callable] = None

    def on_event(self, callback: callable):
        """Register a callback for real-time events (for SSE streaming)."""
        self._event_callback = callback

    def _emit(self, event_type: str, data: dict):
        """Emit an event to the callback and stdout."""
        event = {"type": event_type, **data}
        print(json.dumps(event), flush=True)
        if self._event_callback:
            self._event_callback(event)

    async def setup(self):
        """Initialize agents and load product catalog."""
        # Check engine health
        healthy = await self.client.health()
        if not healthy:
            print("ERROR: Meridian engine not reachable at", self.config.engine_url)
            sys.exit(1)

        # Load products
        self.products = await self.client.get_products()
        self._emit("setup", {
            "products": len(self.products),
            "engine_url": self.config.engine_url,
        })

        # Generate agents
        self.agents = generate_agents(
            num_agents=self.config.num_agents,
            budget_range=self.config.agent_budget_range,
            seed=self.config.seed,
        )
        self._emit("agents_ready", {
            "count": len(self.agents),
            "total_budget_cents": sum(a.budget for a in self.agents),
        })

    async def run_round(self, round_num: int) -> RoundSummary:
        """Execute one round of the simulation."""
        summary = RoundSummary(round_num=round_num)
        tasks = []

        for agent in self.agents:
            if agent.remaining_budget <= 0:
                continue

            # Pick a random product
            product = self.rng.choice(self.products)
            price = product["base_price"]

            # Agent decides whether to buy
            if not agent.wants_to_buy(price, product.get("category", "")):
                continue

            # Pick protocol: agent preference or random from config
            if agent.protocol_preference and agent.protocol_preference in self.config.protocols:
                protocol = agent.protocol_preference.value
            else:
                protocol = self.rng.choice(self.config.protocols).value

            needs_shipping = product.get("requires_shipping", False)

            # Queue the purchase
            tasks.append(self._execute_purchase(
                agent=agent,
                product=product,
                protocol=protocol,
                round_num=round_num,
                needs_shipping=needs_shipping,
            ))

        summary.active_agents = len(tasks)

        if tasks:
            # Run all purchases concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, Exception):
                    summary.fail_count += 1
                    continue
                if isinstance(r, TransactionRecord):
                    summary.transactions.append(r)
                    if r.success:
                        summary.success_count += 1
                        summary.total_volume += r.amount
                        summary.total_fees += r.fee
                    else:
                        summary.fail_count += 1

        self._emit("round_complete", {
            "round": round_num,
            "active_agents": summary.active_agents,
            "success": summary.success_count,
            "failed": summary.fail_count,
            "volume_cents": summary.total_volume,
        })

        return summary

    async def _execute_purchase(
        self,
        agent: AgentProfile,
        product: dict,
        protocol: str,
        round_num: int,
        needs_shipping: bool,
    ) -> TransactionRecord:
        """Execute a single purchase for an agent."""
        record = await self.client.full_purchase(
            agent_id=agent.agent_id,
            product_id=product["id"],
            quantity=1,
            protocol=protocol,
            round_num=round_num,
            product_name=product.get("name", ""),
            needs_shipping=needs_shipping,
        )

        if record.success:
            agent.spent += record.amount
            self._emit("purchase", {
                "agent": agent.agent_id,
                "product": product["name"],
                "protocol": protocol,
                "amount_cents": record.amount,
                "round": round_num,
            })

        return record

    async def run(self) -> SimulationResult:
        """Run the full simulation."""
        start_time = time.time()

        await self.setup()

        self._emit("simulation_start", {
            "agents": self.config.num_agents,
            "rounds": self.config.num_rounds,
            "protocols": [p.value for p in self.config.protocols],
        })

        for round_num in range(1, self.config.num_rounds + 1):
            summary = await self.run_round(round_num)
            self.result.rounds.append(summary)
            self.result.total_transactions += summary.success_count + summary.fail_count
            self.result.total_volume += summary.total_volume

        self.result.duration_seconds = time.time() - start_time

        # Get final protocol metrics from engine
        metrics = await self.client.get_metrics()
        self.result.protocol_summaries = {
            p["protocol"]: p for p in metrics.get("protocols", [])
        }

        self._emit("simulation_complete", {
            "total_transactions": self.result.total_transactions,
            "total_volume_cents": self.result.total_volume,
            "duration_seconds": round(self.result.duration_seconds, 2),
            "protocol_summaries": self.result.protocol_summaries,
        })

        await self.client.close()
        return self.result

    def print_report(self):
        """Print a formatted comparison report."""
        r = self.result
        print("\n" + "=" * 70)
        print("  MERIDIAN SIMULATION REPORT")
        print("=" * 70)
        print(f"  Agents: {self.config.num_agents} | Rounds: {self.config.num_rounds} | Duration: {r.duration_seconds:.1f}s")
        print(f"  Total Transactions: {r.total_transactions} | Volume: ${r.total_volume / 100:.2f}")
        print()

        # Protocol comparison table
        print(f"  {'Protocol':<8} {'Txns':>6} {'Volume':>12} {'Fees':>10} {'Fee%':>7} {'Settle':>10} {'Micropay':>10}")
        print("  " + "-" * 65)

        for proto_name in ["atxp", "x402", "mpp", "acp", "ap2"]:
            p = r.protocol_summaries.get(proto_name, {})
            txns = p.get("total_transactions", 0)
            vol = p.get("total_volume_cents", 0)
            fees = p.get("total_fees_cents", 0)
            settle = p.get("avg_settlement_ms", 0)
            micro = p.get("micropayment_count", 0)
            fee_pct = (fees / vol * 100) if vol > 0 else 0

            print(
                f"  {proto_name.upper():<8} {txns:>6} "
                f"${vol / 100:>10.2f} "
                f"${fees / 100:>8.2f} "
                f"{fee_pct:>6.2f}% "
                f"{settle:>8.0f}ms "
                f"{micro:>10}"
            )

        print()

        # Per-round activity
        print("  Round Activity:")
        for rd in r.rounds:
            bar = "█" * rd.success_count + "░" * rd.fail_count
            print(f"    R{rd.round_num:>3}: {bar} ({rd.success_count} ok, {rd.fail_count} fail, ${rd.total_volume / 100:.2f})")

        print()

        # Agent spending summary
        top_spenders = sorted(self.agents, key=lambda a: a.spent, reverse=True)[:5]
        print("  Top 5 Spenders:")
        for a in top_spenders:
            print(f"    {a.name:<15} ${a.spent / 100:>8.2f} / ${a.budget / 100:.2f} budget")

        print("\n" + "=" * 70)


async def main():
    """Run a simulation. Config from env vars or defaults."""
    import os

    num_agents = int(os.environ.get("MERIDIAN_AGENTS", "50"))
    num_rounds = int(os.environ.get("MERIDIAN_ROUNDS", "10"))
    engine_url = os.environ.get("MERIDIAN_ENGINE_URL", "http://localhost:4080")
    seed = int(os.environ.get("MERIDIAN_SEED", "42"))

    config = SimulationConfig(
        num_agents=num_agents,
        num_rounds=num_rounds,
        protocols=[Protocol.ACP, Protocol.X402, Protocol.AP2, Protocol.MPP, Protocol.ATXP],
        engine_url=engine_url,
        seed=seed,
    )

    engine = SimulationEngine(config)
    await engine.run()

    # Only print report to stderr so stdout stays clean JSON for streaming
    import io
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    engine.print_report()
    report = sys.stdout.getvalue()
    sys.stdout = old_stdout
    print(report, file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
