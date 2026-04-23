"""Structured report generator for Meridian simulation results."""

from .types import AgentProfile, SimulationResult


def _cents_to_dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _pct(numerator: float, denominator: float) -> str:
    if denominator == 0:
        return "0.00%"
    return f"{numerator / denominator * 100:.2f}%"


# Canonical protocol display order
_PROTO_ORDER = ["acp", "ap2", "x402", "mpp", "atxp"]


class ReportGenerator:
    """Generates structured protocol comparison reports from simulation results.

    Pure data analysis — no LLM calls.
    """

    def __init__(self, result: SimulationResult, agents: list[AgentProfile]):
        self.result = result
        self.agents = agents

    def generate(self) -> list[dict]:
        """Return a list of report sections as {title, content, status} dicts."""
        sections: list[dict] = []
        sections.append(self._executive_summary())
        sections.append(self._ecosystem_summary())
        sections.append(self._emergent_world_summary())
        sections.append(self._self_sustainability_signals())
        sections.append(self._float_summary())
        sections.extend(self._per_protocol_sections())
        sections.append(self._comparative_ranking())
        sections.append(self._economics_ranking())
        sections.append(self._route_summary())
        sections.append(self._agent_behavior())
        sections.append(self._micropayment_analysis())
        sections.append(self._recommendations())
        return sections

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _executive_summary(self) -> dict:
        r = self.result
        total_fees = sum(
            p.get("total_fees_cents", 0)
            for p in r.protocol_summaries.values()
        )
        success = sum(
            p.get("successful_transactions", 0)
            for p in r.protocol_summaries.values()
        )
        failed = sum(
            p.get("failed_transactions", 0)
            for p in r.protocol_summaries.values()
        )
        total = success + failed
        lines = [
            f"Agents: {r.config.num_agents}",
            f"Rounds: {r.config.num_rounds}",
            f"Merchants: {sum(state.merchant_count for state in r.ecosystem_summary.values())}",
            f"Protocols tested: {', '.join(p.value.upper() for p in r.config.protocols)}",
            f"Duration: {r.duration_seconds:.1f}s",
            "",
            f"Total transactions: {total} ({success} succeeded, {failed} failed)",
            f"Total volume: {_cents_to_dollars(r.total_volume)}",
            f"Total fees: {_cents_to_dollars(total_fees)}",
            f"Overall success rate: {_pct(success, total)}",
        ]
        return {"title": "Executive Summary", "content": "\n".join(lines), "status": "ok"}

    def _ecosystem_summary(self) -> dict:
        if not self.result.ecosystem_summary:
            return {"title": "Ecosystem Dynamics", "content": "No ecosystem data available.", "status": "empty"}

        lines = ["Rail adoption and scaling state:"]
        for proto_name in _PROTO_ORDER:
            state = self.result.ecosystem_summary.get(proto_name)
            if not state:
                continue
            lines.append(
                f"  {proto_name.upper()}: merchants={state.merchant_count}, "
                f"network_effect={state.network_effect:.2f}, reliability={state.reliability:.2%}, "
                f"congestion={state.congestion:.2f}, scale_pressure={state.scale_pressure:.2f}"
            )
        return {"title": "Ecosystem Dynamics", "content": "\n".join(lines), "status": "ok"}

    def _emergent_world_summary(self) -> dict:
        memory_count = len(self.result.agent_memory_log)
        world_count = len(self.result.world_events)
        if memory_count == 0 and world_count == 0 and not self.result.trust_summary:
            return {
                "title": "Emergent Agent Economy",
                "content": "No agent memory or world-event data available.",
                "status": "empty",
            }

        lines = [
            f"World seed: {self.result.config.world_seed}",
            f"Agent memory events: {memory_count}",
            f"World events: {world_count}",
        ]
        if self.result.config.scenario_prompt:
            lines.append(f"Scenario prompt: {self.result.config.scenario_prompt}")

        if self.result.trust_summary:
            lines.append("")
            lines.append("Protocol trust across agents:")
            for proto_name in _PROTO_ORDER:
                trust = self.result.trust_summary.get(proto_name)
                if not trust:
                    continue
                lines.append(
                    f"  {proto_name.upper()}: avg={trust.get('avg', 0):.2f}, "
                    f"min={trust.get('min', 0):.2f}, max={trust.get('max', 0):.2f}"
                )

        if self.result.world_events:
            lines.append("")
            lines.append("Recent world events:")
            for event in self.result.world_events[-5:]:
                lines.append(f"  R{event.round_num}: {event.summary}")

        return {"title": "Emergent Agent Economy", "content": "\n".join(lines), "status": "ok"}

    def _self_sustainability_signals(self) -> dict:
        treasury_ok = [
            event for event in self.result.world_events
            if event.event_type == "treasury_rebalance"
        ]
        treasury_failed = [
            event for event in self.result.world_events
            if event.event_type == "treasury_rebalance_failed"
        ]
        treasury_posture_events = [
            event for event in self.result.world_events
            if event.event_type == "treasury_posture"
        ]
        route_events = [
            event for event in self.result.world_events
            if event.event_type == "route_pressure"
        ]
        has_margin = any(
            state.operator_margin_cents or state.fee_revenue_cents or state.infrastructure_cost_cents
            for state in self.result.ecosystem_summary.values()
        )
        if (
            not treasury_ok
            and not treasury_failed
            and not treasury_posture_events
            and not route_events
            and not self.result.treasury_posture_summary
            and not self.result.route_pressure_summary
            and not has_margin
        ):
            return {
                "title": "Self-Sustainability Signals",
                "content": "No treasury rebalance, route pressure, or rail margin data available.",
                "status": "empty",
            }

        lines = [
            f"Treasury rebalances: {len(treasury_ok)} succeeded, {len(treasury_failed)} failed",
            f"Treasury posture events: {len(treasury_posture_events)}",
            f"Route pressure events: {len(route_events)}",
        ]

        if self.result.treasury_posture_summary:
            lines.append("")
            lines.append("Treasury posture watchlist:")
            for merchant in self.result.treasury_posture_summary[:5]:
                lines.append(
                    f"  {merchant['merchant']}: max_shortfall="
                    f"{_cents_to_dollars(int(merchant['max_preferred_shortfall_cents']))}, "
                    f"min_preferred={float(merchant['min_preferred_ratio']) * 100:.1f}%, "
                    f"ready_rounds={merchant['rebalance_ready_rounds']}"
                )

        if self.result.route_pressure_summary:
            lines.append("")
            lines.append("Most pressured routes:")
            for route in self.result.route_pressure_summary[:5]:
                lines.append(
                    f"  {route['route_id']}: max={float(route['max_capacity_ratio']) * 100:.1f}%, "
                    f"usage={_cents_to_dollars(int(route['total_usage_cents']))}, "
                    f"rounds={route['pressure_rounds']}"
                )

        if self.result.ecosystem_summary:
            lines.append("")
            lines.append("Rail margin pressure:")
            states = sorted(
                self.result.ecosystem_summary.items(),
                key=lambda item: item[1].operator_margin_cents,
            )
            for name, state in states:
                lines.append(
                    f"  {name.upper()}: margin={_cents_to_dollars(state.operator_margin_cents)}, "
                    f"revenue={_cents_to_dollars(state.fee_revenue_cents)}, "
                    f"infra={_cents_to_dollars(state.infrastructure_cost_cents)}, "
                    f"scale_pressure={state.scale_pressure:.2f}"
                )

        recent = (treasury_ok + treasury_failed + treasury_posture_events + route_events)[-5:]
        if recent:
            lines.append("")
            lines.append("Recent sustainability events:")
            for event in recent:
                lines.append(f"  R{event.round_num}: {event.summary}")

        status = "warn" if treasury_failed or any(
            route.get("max_capacity_ratio", 0) >= 1.0
            for route in self.result.route_pressure_summary
        ) else "ok"
        return {"title": "Self-Sustainability Signals", "content": "\n".join(lines), "status": status}

    def _float_summary(self) -> dict:
        if not self.result.float_summary:
            return {"title": "Stablecoin Float", "content": "No float data available.", "status": "empty"}

        lines = ["Stablecoin float by domain:"]
        for domain, amount in sorted(self.result.float_summary.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"  {domain}: {_cents_to_dollars(amount)}")
        return {"title": "Stablecoin Float", "content": "\n".join(lines), "status": "ok"}

    def _per_protocol_sections(self) -> list[dict]:
        sections = []
        for proto_name in _PROTO_ORDER:
            pm = self.result.protocol_summaries.get(proto_name)
            if pm is None:
                continue

            txns = pm.get("total_transactions", 0)
            success = pm.get("successful_transactions", 0)
            failed = pm.get("failed_transactions", 0)
            vol = pm.get("total_volume_cents", 0)
            fees = pm.get("total_fees_cents", 0)
            avg_exec = pm.get("avg_settlement_ms", 0.0)
            micro = pm.get("micropayment_count", 0)

            lines = [
                f"Transactions: {txns} ({success} ok, {failed} failed)",
                f"Volume: {_cents_to_dollars(vol)}",
                f"Fees: {_cents_to_dollars(fees)} ({_pct(fees, vol)} of volume)",
                f"Avg execution time: {avg_exec:.3f} ms",
                f"Micropayments (< $1): {micro}",
                f"Success rate: {_pct(success, txns)}",
            ]

            status = "ok"
            if txns == 0:
                status = "empty"
            elif failed > success:
                status = "warn"

            sections.append({
                "title": f"Protocol: {proto_name.upper()}",
                "content": "\n".join(lines),
                "status": status,
            })
        return sections

    def _comparative_ranking(self) -> dict:
        protos = self._active_protocols()
        if not protos:
            return {"title": "Comparative Ranking", "content": "No protocol data available.", "status": "empty"}

        def _get(name: str, key: str, default=0):
            return self.result.protocol_summaries.get(name, {}).get(key, default)

        # Rank by speed (lower is better)
        by_speed = sorted(protos, key=lambda p: _get(p, "avg_settlement_ms", float("inf")))

        # Rank by cost (lower fee% is better)
        def fee_ratio(p: str) -> float:
            vol = _get(p, "total_volume_cents", 0)
            fees = _get(p, "total_fees_cents", 0)
            return fees / vol if vol > 0 else float("inf")

        by_cost = sorted(protos, key=fee_ratio)

        # Rank by reliability (higher success rate is better)
        def success_rate(p: str) -> float:
            txns = _get(p, "total_transactions", 0)
            ok = _get(p, "successful_transactions", 0)
            return ok / txns if txns > 0 else 0.0

        by_reliability = sorted(protos, key=success_rate, reverse=True)

        lines = [
            "Fastest settlement:",
            *[f"  {i+1}. {p.upper()} ({_get(p, 'avg_settlement_ms', 0):.3f} ms)" for i, p in enumerate(by_speed)],
            "",
            "Lowest fee ratio:",
            *[f"  {i+1}. {p.upper()} ({_pct(_get(p, 'total_fees_cents'), _get(p, 'total_volume_cents'))})" for i, p in enumerate(by_cost)],
            "",
            "Most reliable:",
            *[f"  {i+1}. {p.upper()} ({_pct(_get(p, 'successful_transactions'), _get(p, 'total_transactions'))})" for i, p in enumerate(by_reliability)],
        ]
        return {"title": "Comparative Ranking", "content": "\n".join(lines), "status": "ok"}

    def _economics_ranking(self) -> dict:
        if not self.result.ecosystem_summary:
            return {"title": "Protocol Economics", "content": "No economics data available.", "status": "empty"}

        states = [
            (name, self.result.ecosystem_summary[name])
            for name in _PROTO_ORDER
            if name in self.result.ecosystem_summary
        ]
        by_margin = sorted(states, key=lambda item: item[1].operator_margin_cents, reverse=True)
        by_scale = sorted(states, key=lambda item: item[1].network_effect, reverse=True)

        lines = ["Best unit economics:"]
        for idx, (name, state) in enumerate(by_margin, start=1):
            lines.append(
                f"  {idx}. {name.upper()} "
                f"(margin={_cents_to_dollars(state.operator_margin_cents)}, "
                f"volume={_cents_to_dollars(state.gross_volume_cents)})"
            )

        lines.append("")
        lines.append("Best ecosystem pull:")
        for idx, (name, state) in enumerate(by_scale, start=1):
            lines.append(
                f"  {idx}. {name.upper()} "
                f"(network_effect={state.network_effect:.2f}, merchants={state.merchant_count})"
            )

        return {"title": "Protocol Economics", "content": "\n".join(lines), "status": "ok"}

    def _route_summary(self) -> dict:
        if not self.result.route_usage_summary:
            return {"title": "Route Usage", "content": "No route usage data available.", "status": "empty"}

        lines = ["Most used settlement routes:"]
        for route, count in sorted(self.result.route_usage_summary.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"  {route}: {count}")
        return {"title": "Route Usage", "content": "\n".join(lines), "status": "ok"}

    def _agent_behavior(self) -> dict:
        top_spenders = sorted(self.agents, key=lambda a: a.spent, reverse=True)[:10]

        # Count transactions per agent from round data
        agent_txn_counts: dict[str, int] = {}
        agent_proto_counts: dict[str, dict[str, int]] = {}
        for rd in self.result.rounds:
            for tx in rd.transactions:
                if tx.success:
                    agent_txn_counts[tx.agent_id] = agent_txn_counts.get(tx.agent_id, 0) + 1
                    if tx.agent_id not in agent_proto_counts:
                        agent_proto_counts[tx.agent_id] = {}
                    agent_proto_counts[tx.agent_id][tx.protocol] = (
                        agent_proto_counts[tx.agent_id].get(tx.protocol, 0) + 1
                    )

        most_active = sorted(agent_txn_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

        lines = ["Top spenders:"]
        for a in top_spenders:
            if a.spent == 0:
                continue
            lines.append(
                f"  {a.name}: {_cents_to_dollars(a.spent)} of {_cents_to_dollars(a.budget)} "
                f"({_pct(a.spent, a.budget)} of budget)"
            )

        lines.append("")
        lines.append("Most active (by transaction count):")
        for agent_id, count in most_active:
            protos = agent_proto_counts.get(agent_id, {})
            proto_str = ", ".join(f"{p.upper()}={c}" for p, c in sorted(protos.items(), key=lambda kv: kv[1], reverse=True))
            lines.append(f"  {agent_id}: {count} txns ({proto_str})")

        # Protocol preference distribution
        lines.append("")
        lines.append("Protocol preferences across all agents:")
        global_proto: dict[str, int] = {}
        for protos in agent_proto_counts.values():
            for p, c in protos.items():
                global_proto[p] = global_proto.get(p, 0) + c
        total_txns = sum(global_proto.values()) or 1
        for p in _PROTO_ORDER:
            c = global_proto.get(p, 0)
            if c > 0:
                lines.append(f"  {p.upper()}: {c} txns ({_pct(c, total_txns)})")

        return {"title": "Agent Behavior Analysis", "content": "\n".join(lines), "status": "ok"}

    def _micropayment_analysis(self) -> dict:
        protos = self._active_protocols()

        def _get(name: str, key: str, default=0):
            return self.result.protocol_summaries.get(name, {}).get(key, default)

        micro_protos = [(p, _get(p, "micropayment_count", 0)) for p in protos]
        micro_protos.sort(key=lambda kv: kv[1], reverse=True)

        total_micro = sum(c for _, c in micro_protos)

        if total_micro == 0:
            return {
                "title": "Micropayment Analysis",
                "content": "No micropayments (< $1.00) recorded in this simulation.",
                "status": "empty",
            }

        lines = [
            f"Total micropayments (< $1.00): {total_micro}",
            "",
            "By protocol:",
        ]
        for p, count in micro_protos:
            if count == 0:
                continue
            vol = _get(p, "total_volume_cents", 0)
            fees = _get(p, "total_fees_cents", 0)
            txns = _get(p, "total_transactions", 0)
            micro_share = _pct(count, txns) if txns else "N/A"
            lines.append(
                f"  {p.upper()}: {count} micropayments ({micro_share} of its txns), "
                f"fee ratio {_pct(fees, vol)}"
            )

        lines.append("")
        lines.append("Protocols NOT suited for micropayments (no sub-$1 txns or high fee ratios):")
        for p in protos:
            mc = _get(p, "micropayment_count", 0)
            vol = _get(p, "total_volume_cents", 0)
            fees = _get(p, "total_fees_cents", 0)
            fee_ratio = fees / vol if vol > 0 else 0
            if mc == 0 or fee_ratio > 0.10:
                reason = "no micropayments" if mc == 0 else f"high fee ratio ({_pct(fees, vol)})"
                lines.append(f"  {p.upper()}: {reason}")

        return {"title": "Micropayment Analysis", "content": "\n".join(lines), "status": "ok"}

    def _recommendations(self) -> dict:
        protos = self._active_protocols()
        if not protos:
            return {"title": "Recommendations", "content": "No data to analyze.", "status": "empty"}

        def _get(name: str, key: str, default=0):
            return self.result.protocol_summaries.get(name, {}).get(key, default)

        def fee_ratio(p: str) -> float:
            vol = _get(p, "total_volume_cents", 0)
            fees = _get(p, "total_fees_cents", 0)
            return fees / vol if vol > 0 else float("inf")

        def success_rate(p: str) -> float:
            txns = _get(p, "total_transactions", 0)
            ok = _get(p, "successful_transactions", 0)
            return ok / txns if txns > 0 else 0.0

        recs: list[str] = []

        # Best for micropayments
        micro_candidates = [(p, _get(p, "micropayment_count", 0)) for p in protos if _get(p, "micropayment_count", 0) > 0]
        if micro_candidates:
            best_micro = min(micro_candidates, key=lambda kv: fee_ratio(kv[0]))
            recs.append(
                f"Micropayments: {best_micro[0].upper()} — lowest fee ratio among protocols "
                f"that handled sub-$1 transactions ({_pct(_get(best_micro[0], 'total_fees_cents'), _get(best_micro[0], 'total_volume_cents'))})."
            )

        # Best for high-value
        hv_best = min(protos, key=fee_ratio)
        recs.append(
            f"High-value transactions: {hv_best.upper()} — lowest overall fee ratio "
            f"({_pct(_get(hv_best, 'total_fees_cents'), _get(hv_best, 'total_volume_cents'))})."
        )

        # Best for speed
        speed_best = min(protos, key=lambda p: _get(p, "avg_settlement_ms", float("inf")))
        recs.append(
            f"Latency-sensitive use cases: {speed_best.upper()} — fastest avg settlement "
            f"({_get(speed_best, 'avg_settlement_ms', 0):.3f} ms)."
        )

        # Best for reliability
        rel_best = max(protos, key=success_rate)
        recs.append(
            f"Mission-critical commerce: {rel_best.upper()} — highest success rate "
            f"({_pct(_get(rel_best, 'successful_transactions'), _get(rel_best, 'total_transactions'))})."
        )

        if self.result.ecosystem_summary:
            eco_best = max(
                self.result.ecosystem_summary.items(),
                key=lambda item: item[1].operator_margin_cents,
            )
            recs.append(
                f"Ecosystem operator economics: {eco_best[0].upper()} — strongest simulated "
                f"margin at {_cents_to_dollars(eco_best[1].operator_margin_cents)}."
            )

        # Caution flags
        cautions: list[str] = []
        for p in protos:
            sr = success_rate(p)
            if sr < 0.90 and _get(p, "total_transactions", 0) > 0:
                cautions.append(
                    f"  {p.upper()}: success rate {_pct(_get(p, 'successful_transactions'), _get(p, 'total_transactions'))} "
                    f"— investigate failure causes before production use."
                )
            fr = fee_ratio(p)
            if fr > 0.05 and _get(p, "total_volume_cents", 0) > 0:
                cautions.append(
                    f"  {p.upper()}: fee ratio {_pct(_get(p, 'total_fees_cents'), _get(p, 'total_volume_cents'))} "
                    f"— may erode margins on low-value goods."
                )

        content_lines = ["Best fit by use case:", ""]
        content_lines.extend(f"  {r}" for r in recs)

        if cautions:
            content_lines.append("")
            content_lines.append("Caution flags:")
            content_lines.extend(cautions)

        return {"title": "Recommendations", "content": "\n".join(content_lines), "status": "ok"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _active_protocols(self) -> list[str]:
        """Return protocol names that have data, in canonical order."""
        return [p for p in _PROTO_ORDER if p in self.result.protocol_summaries]
