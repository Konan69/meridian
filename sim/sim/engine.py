"""Meridian simulation engine — orchestrates agents across protocols."""

import asyncio
import json
import os
import random
import sys
import time
from typing import Optional

from .agents import generate_agents
from .commerce import CommerceClient
from .llm import LLMDecisionEngine
from .types import (
    AgentProfile,
    Protocol,
    RoundSummary,
    SimulationConfig,
    SimulationResult,
    TransactionRecord,
)


class SimulationEngine:
    """Runs multi-protocol commerce simulations with rule-based or LLM-powered agents."""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.client = CommerceClient(config.engine_url)
        self.agents: list[AgentProfile] = []
        self.products: list[dict] = []
        self.result = SimulationResult(config=config)
        self.rng = random.Random(config.seed)
        self.llm_engine: Optional[LLMDecisionEngine] = None

        # Initialize LLM engine if enabled
        if config.use_llm:
            api_key = os.environ.get("OPENCODE_API_KEY", "")
            if api_key:
                self.llm_engine = LLMDecisionEngine(
                    api_key=api_key,
                    model=config.llm_model,
                )
                self._emit("llm_enabled", {"model": config.llm_model})
            else:
                self._emit("llm_fallback", {
                    "reason": "OPENCODE_API_KEY not set, using rule-based decisions",
                })

    def _emit(self, event_type: str, data: dict):
        """Emit a JSON event to stdout for streaming."""
        print(json.dumps({"type": event_type, **data}), flush=True)

    async def setup(self):
        """Initialize agents and load product catalog."""
        healthy = await self.client.health()
        if not healthy:
            self._emit("error", {"message": f"Engine not reachable at {self.config.engine_url}"})
            sys.exit(1)

        self.products = await self.client.get_products()
        self._emit("setup", {"products": len(self.products), "engine_url": self.config.engine_url})

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
        proto_idx = 0  # flat round-robin across protocols

        if self.llm_engine:
            # LLM-powered decisions
            candidates = []
            for agent in self.agents:
                if agent.remaining_budget <= 0:
                    continue
                product = self.rng.choice(self.products)
                candidates.append((agent, product))

            # Run LLM decisions concurrently
            protocol_strs = [p.value for p in self.config.protocols]
            decision_coros = [
                self.llm_engine.decide(agent, product, self.config.protocols, self.rng)
                for agent, product in candidates
            ]
            decisions = await asyncio.gather(*decision_coros, return_exceptions=True)

            for (agent, product), decision in zip(candidates, decisions):
                if isinstance(decision, Exception):
                    self._emit("llm_error", {"agent": agent.agent_id, "error": str(decision)})
                    continue
                if not decision.get("buy", False):
                    continue

                protocol = decision.get("protocol", protocol_strs[0])
                if protocol not in protocol_strs:
                    protocol = protocol_strs[0]

                needs_shipping = product.get("requires_shipping", False)
                tasks.append(self._execute_purchase(
                    agent=agent,
                    product=product,
                    protocol=protocol,
                    round_num=round_num,
                    needs_shipping=needs_shipping,
                ))
        else:
            # Rule-based decisions
            for agent in self.agents:
                if agent.remaining_budget <= 0:
                    continue

                product = self.rng.choice(self.products)
                price = product["base_price"]
                category = product.get("category", "")

                if not agent.wants_to_buy(price, category, self.rng):
                    continue

                # FLAT distribution: round-robin across protocols for fair comparison
                protocol = self.config.protocols[proto_idx % len(self.config.protocols)].value
                proto_idx += 1

                needs_shipping = product.get("requires_shipping", False)
                tasks.append(self._execute_purchase(
                    agent=agent,
                    product=product,
                    protocol=protocol,
                    round_num=round_num,
                    needs_shipping=needs_shipping,
                ))

        summary.active_agents = len(tasks)

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, Exception):
                    summary.fail_count += 1
                    self._emit("error", {"round": round_num, "error": str(r)})
                    continue
                if isinstance(r, TransactionRecord):
                    summary.transactions.append(r)
                    if r.success:
                        summary.success_count += 1
                        summary.total_volume += r.amount
                        summary.total_fees += r.fee
                    else:
                        summary.fail_count += 1
                        self._emit("purchase_failed", {
                            "agent": r.agent_id, "protocol": r.protocol,
                            "error": r.error, "round": round_num,
                        })

        self._emit("round_complete", {
            "round": round_num,
            "active_agents": summary.active_agents,
            "success": summary.success_count,
            "failed": summary.fail_count,
            "volume_cents": summary.total_volume,
            "fees_cents": summary.total_fees,
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
            agent_address=agent.address if needs_shipping else None,
        )

        if record.success:
            agent.spent += record.amount
            self._emit("purchase", {
                "agent": agent.agent_id,
                "product": product["name"],
                "protocol": protocol,
                "amount_cents": record.amount,
                "fee_cents": record.fee,
                "settlement_ms": record.settlement_ms,
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

        metrics = await self.client.get_metrics()
        self.result.protocol_summaries = {
            p["protocol"]: p for p in metrics.get("protocols", [])
        }

        completion_data = {
            "total_transactions": self.result.total_transactions,
            "total_volume_cents": self.result.total_volume,
            "duration_seconds": round(self.result.duration_seconds, 2),
            "protocol_summaries": self.result.protocol_summaries,
        }
        if self.llm_engine:
            completion_data["llm_usage"] = self.llm_engine.usage_summary()
        self._emit("simulation_complete", completion_data)

        await self.client.close()
        return self.result

    def print_report(self, file=sys.stderr):
        """Print a formatted comparison report to the given file (default stderr)."""
        r = self.result
        p = lambda *args, **kw: print(*args, **kw, file=file)

        p("\n" + "=" * 70)
        p("  MERIDIAN SIMULATION REPORT")
        p("=" * 70)
        p(f"  Agents: {self.config.num_agents} | Rounds: {self.config.num_rounds} | Duration: {r.duration_seconds:.1f}s")
        p(f"  Total Transactions: {r.total_transactions} | Volume: ${r.total_volume / 100:.2f}")
        p()

        p(f"  {'Protocol':<8} {'Txns':>6} {'OK':>5} {'Fail':>5} {'Volume':>12} {'Fees':>10} {'Fee%':>7} {'Avg Exec':>12} {'Micropay':>10}")
        p("  " + "-" * 80)

        for proto_name in ["atxp", "x402", "mpp", "acp", "ap2"]:
            pm = r.protocol_summaries.get(proto_name, {})
            txns = pm.get("total_transactions", 0)
            success = pm.get("successful_transactions", 0)
            failed = pm.get("failed_transactions", 0)
            vol = pm.get("total_volume_cents", 0)
            fees = pm.get("total_fees_cents", 0)
            avg_exec = pm.get("avg_settlement_ms", 0)  # this is now real avg execution ms
            micro = pm.get("micropayment_count", 0)
            fee_pct = (fees / vol * 100) if vol > 0 else 0

            p(
                f"  {proto_name.upper():<8} {txns:>6} {success:>5} {failed:>5} "
                f"${vol / 100:>10.2f} "
                f"${fees / 100:>8.2f} "
                f"{fee_pct:>6.2f}% "
                f"{avg_exec:>10.3f}ms "
                f"{micro:>10}"
            )

        p()
        p("  Round Activity:")
        for rd in r.rounds:
            bar = "█" * rd.success_count + "░" * rd.fail_count
            p(f"    R{rd.round_num:>3}: {bar} ({rd.success_count} ok, {rd.fail_count} fail, ${rd.total_volume / 100:.2f})")

        p()
        top_spenders = sorted(self.agents, key=lambda a: a.spent, reverse=True)[:5]
        p("  Top 5 Spenders:")
        for a in top_spenders:
            p(f"    {a.name:<15} ${a.spent / 100:>8.2f} / ${a.budget / 100:.2f} budget")

        p("\n" + "=" * 70)


async def main():
    """Run a simulation. Config from env vars or defaults."""

    use_llm = os.environ.get("MERIDIAN_USE_LLM", "").lower() in ("1", "true", "yes")
    config = SimulationConfig(
        num_agents=int(os.environ.get("MERIDIAN_AGENTS", "50")),
        num_rounds=int(os.environ.get("MERIDIAN_ROUNDS", "10")),
        protocols=[Protocol.ACP, Protocol.X402, Protocol.AP2, Protocol.MPP, Protocol.ATXP],
        engine_url=os.environ.get("MERIDIAN_ENGINE_URL", "http://localhost:4080"),
        seed=int(os.environ.get("MERIDIAN_SEED", "42")),
        use_llm=use_llm,
        llm_model=os.environ.get("MERIDIAN_LLM_MODEL", "minimax-m2.5-free"),
    )

    engine = SimulationEngine(config)
    await engine.run()
    engine.print_report()


if __name__ == "__main__":
    asyncio.run(main())
