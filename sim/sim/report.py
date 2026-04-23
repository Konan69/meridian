"""Structured report generator for Meridian simulation results."""

from .protocol_labels import (
    normalize_protocol_labels_in_text,
    protocol_display_label,
    protocol_list_label,
)
from .types import AgentProfile, SimulationResult


def _cents_to_dollars(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _pct(numerator: float, denominator: float) -> str:
    if denominator == 0:
        return "0.00%"
    return f"{numerator / denominator * 100:.2f}%"


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _route_pressure_rows_from_events(route_events: list[object]) -> list[dict]:
    rows: dict[str, dict] = {}
    for event in route_events:
        data = getattr(event, "data", None)
        if not isinstance(data, dict):
            continue

        reason = str(data.get("reason") or data.get("error") or "")
        source_domain = data.get("source_domain") or "unknown_source"
        target_domain = data.get("target_domain") or "unknown_target"
        route_id = str(data.get("route_id") or "")
        if (
            not route_id
            and reason == "no_feasible_rebalance_route"
            and source_domain != "unknown_source"
            and target_domain != "unknown_target"
        ):
            route_id = f"treasury_rebalance_unroutable:{source_domain}->{target_domain}"
        if not route_id:
            continue
        protocols = data.get("protocols")
        if not isinstance(protocols, list):
            protocols = data.get("accepted_protocols")
        if not isinstance(protocols, list):
            actor_protocol = getattr(event, "protocol", None) or getattr(event, "actor_id", None)
            protocols = [actor_protocol] if actor_protocol else []

        row = rows.setdefault(
            route_id,
            {
                "route_id": route_id,
                "source_domain": source_domain,
                "target_domain": target_domain,
                "primitive": data.get("primitive") or "unknown",
                "protocols": protocols,
                "total_usage_cents": 0,
                "max_capacity_ratio": 0.0,
                "pressure_rounds": 0,
                "last_pressure_level": "observed",
                "_source": "world_events.route_pressure",
            },
        )
        if not row.get("protocols") and protocols:
            row["protocols"] = protocols
        row["total_usage_cents"] += _as_int(
            data.get("total_usage_cents", data.get("usage_cents", data.get("amount_cents", 0)))
        )
        row["max_capacity_ratio"] = max(
            _as_float(row.get("max_capacity_ratio", 0)),
            _as_float(data.get("max_capacity_ratio", data.get("capacity_ratio", 0))),
        )

        pressure_level = str(
            data.get("last_pressure_level")
            or data.get("pressure_level")
            or row.get("last_pressure_level")
            or "observed"
        )
        if pressure_level != "low":
            row["pressure_rounds"] += 1
        row["last_pressure_level"] = pressure_level

        reason = str(reason or row.get("reason") or "")
        if reason:
            row["reason"] = reason

        failure_count = max(
            _as_int(row.get("failure_count", 0)),
            _as_int(data.get("failure_count", 0)),
        )
        if failure_count:
            row["failure_count"] = failure_count

        merchant = data.get("merchant") or data.get("merchant_id") or row.get("merchant")
        if merchant:
            row["merchant"] = merchant

    return sorted(
        rows.values(),
        key=lambda route: (
            _as_float(route.get("max_capacity_ratio", 0)),
            _as_int(route.get("total_usage_cents", 0)),
            str(route.get("route_id", "")),
        ),
        reverse=True,
    )


def _merchant_switch_route_score_lines(events: list[object], limit: int = 5) -> list[str]:
    entries: list[tuple[str, int, str, str, float, float, float, str]] = []
    for event in events:
        if len(entries) >= limit:
            break
        if getattr(event, "event_type", None) != "merchant_protocol_mix_changed":
            continue
        data = getattr(event, "data", None)
        if not isinstance(data, dict):
            continue
        evidence = data.get("evidence")
        if not isinstance(evidence, dict):
            continue

        pressure_drag = _as_float(evidence.get("route_score_pressure_drag", 0.0))
        sustainability_lift = _as_float(evidence.get("route_score_sustainability_lift", 0.0))
        route_score = _as_float(evidence.get("route_score", 0.0))
        if pressure_drag == 0 and sustainability_lift == 0:
            continue

        round_num = _as_int(getattr(event, "round_num", data.get("round", 0)))
        merchant = str(data.get("merchant") or data.get("merchant_id") or "unknown merchant")
        entries.append(
            (
                merchant,
                round_num,
                str(data.get("action") or "changed"),
                protocol_display_label(data.get("protocol")),
                route_score,
                pressure_drag,
                sustainability_lift,
                str(data.get("reason") or "unknown"),
            )
        )

    lines: list[str] = []
    current_merchant: str | None = None
    for merchant, round_num, action, protocol, route_score, pressure_drag, sustainability_lift, reason in sorted(
        entries,
        key=lambda entry: (entry[0].lower(), entry[1], entry[2], entry[3]),
    ):
        if merchant != current_merchant:
            lines.append(f"  {merchant}:")
            current_merchant = merchant
        lines.extend(
            [
                f"    R{round_num}: {action} {protocol} after route-score evidence",
                f"      score {route_score:.2f}; pressure {pressure_drag:.2f}; "
                f"sustain {sustainability_lift:+.2f}; reason {reason}",
            ]
        )
    return lines


def _world_event_readout_summary(event: object) -> str:
    summary = normalize_protocol_labels_in_text(str(getattr(event, "summary", "")))
    if getattr(event, "event_type", None) != "merchant_protocol_mix_changed":
        return summary

    data = getattr(event, "data", None)
    if not isinstance(data, dict):
        return summary
    evidence = data.get("evidence")
    if not isinstance(evidence, dict):
        return summary

    pressure_drag = _as_float(evidence.get("route_score_pressure_drag", 0.0))
    sustainability_lift = _as_float(evidence.get("route_score_sustainability_lift", 0.0))
    if pressure_drag == 0 and sustainability_lift == 0:
        return summary

    route_score = _as_float(evidence.get("route_score", 0.0))
    protocol = protocol_display_label(data.get("protocol") or getattr(event, "protocol", None))
    return (
        f"{summary} Route-score evidence for {protocol}: score {route_score:.2f}, "
        f"pressure drag {pressure_drag:.2f}, sustainability lift {sustainability_lift:+.2f}."
    )


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
            f"Protocols tested: {', '.join(protocol_display_label(p) for p in r.config.protocols)}",
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
                f"  {protocol_display_label(proto_name)}: merchants={state.merchant_count}, "
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
                    f"  {protocol_display_label(proto_name)}: avg={trust.get('avg', 0):.2f}, "
                    f"min={trust.get('min', 0):.2f}, max={trust.get('max', 0):.2f}"
                )

        if self.result.world_events:
            lines.append("")
            lines.append("Recent world events:")
            for event in self.result.world_events[-5:]:
                lines.append(
                    f"  R{event.round_num}: {_world_event_readout_summary(event)}"
                )

            switch_lines = _merchant_switch_route_score_lines(self.result.world_events)
            if switch_lines:
                lines.append("")
                lines.append("Route-score merchant changes:")
                lines.extend(switch_lines)

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
        merchant_switch_events = [
            event for event in self.result.world_events
            if event.event_type in {"merchant_protocol_mix_changed", "merchant_switch"}
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
            and not merchant_switch_events
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
            f"Merchant protocol changes: {len(merchant_switch_events)}",
        ]
        route_pressure_rows = (
            self.result.route_pressure_summary
            or _route_pressure_rows_from_events(route_events)
        )

        if merchant_switch_events:
            latest_switch = sorted(
                merchant_switch_events,
                key=lambda event: (event.round_num, event.summary),
            )[-1]
            data = latest_switch.data if isinstance(latest_switch.data, dict) else {}
            merchant = str(
                data.get("merchant")
                or data.get("merchant_id")
                or latest_switch.actor_id
                or "unknown merchant"
            )
            action = str(data.get("action") or "changed")
            protocol = protocol_display_label(data.get("protocol") or latest_switch.protocol)
            reason = str(data.get("reason") or "unknown")
            lines.append(
                f"Merchant adaptation: R{latest_switch.round_num} latest of "
                f"{len(merchant_switch_events)} protocol changes: {merchant} {action} "
                f"{protocol} after {reason.replace('_', ' ')}."
            )

        if route_pressure_rows:
            peak_route = sorted(
                route_pressure_rows,
                key=lambda route: (
                    -_as_float(route.get("max_capacity_ratio", 0)),
                    str(route.get("route_id", "")),
                ),
            )[0]
            pressure = _as_float(peak_route.get("max_capacity_ratio", 0))
            route_id = str(peak_route.get("route_id") or "unknown_route")
            usage_cents = _as_int(peak_route.get("total_usage_cents", 0))
            pressure_rounds = _as_int(peak_route.get("pressure_rounds", 0))
            round_label = "pressure round" if pressure_rounds == 1 else "pressure rounds"
            pressure_level = str(peak_route.get("last_pressure_level") or "observed")
            if pressure >= 1.0:
                route_action = (
                    "reroute demand or add float before more volume lands here"
                )
            elif pressure >= 0.7:
                route_action = (
                    "watch agent memory and treasury mix before raising volume"
                )
            else:
                route_action = (
                    "route capacity is available; treasury mix, margin, and trust carry more signal"
                )
            lines.append(
                f"Readout: {route_id} peaked at {pressure * 100:.1f}% capacity "
                f"({pressure_level}) across {pressure_rounds} {round_label} with "
                f"{_cents_to_dollars(usage_cents)} reserved principal; {route_action}."
            )
            unroutable = [
                route for route in route_pressure_rows
                if (
                    str(route.get("route_id", "")).startswith("treasury_rebalance_unroutable:")
                    or route.get("reason") == "no_feasible_rebalance_route"
                )
            ]
            if unroutable:
                blocked = sorted(
                    unroutable,
                    key=lambda route: (
                        -_as_float(route.get("max_capacity_ratio", 0)),
                        -_as_int(route.get("total_usage_cents", route.get("usage_cents", 0))),
                        str(route.get("route_id", "")),
                    ),
                )[0]
                blocked_route = str(blocked.get("route_id") or "treasury_rebalance_unroutable")
                source = str(blocked.get("source_domain") or "unknown_source")
                target = str(blocked.get("target_domain") or "unknown_target")
                protocols = protocol_list_label(blocked.get("protocols"))
                pressure_rounds = _as_int(blocked.get("pressure_rounds", blocked.get("failure_count", 0)))
                round_label = "pressure round" if pressure_rounds == 1 else "pressure rounds"
                blocked_cents = _as_int(blocked.get("total_usage_cents", blocked.get("usage_cents", 0)))
                raw_parts = []
                if blocked.get("_source") == "world_events.route_pressure":
                    reason = str(blocked.get("reason") or "")
                    failure_count = _as_int(blocked.get("failure_count", 0))
                    level = str(blocked.get("last_pressure_level") or "observed")
                    if reason:
                        raw_parts.append(f"reason {reason}")
                    if failure_count:
                        raw_parts.append(f"failure_count {failure_count}")
                    if level != "observed":
                        raw_parts.append(f"pressure_level {level}")
                raw_suffix = f"; {', '.join(raw_parts)}" if raw_parts else ""
                lines.append(
                    f"Unroutable treasury pressure: {blocked_route} reached "
                    f"{_as_float(blocked.get('max_capacity_ratio', 0)) * 100:.1f}% capacity "
                    f"across {pressure_rounds} {round_label} with "
                    f"{_cents_to_dollars(blocked_cents)} blocked demand; protocols "
                    f"{protocols} had no feasible {source} -> {target} route{raw_suffix}."
                )

        if treasury_failed:
            latest_failure = sorted(
                treasury_failed,
                key=lambda event: (event.round_num, event.summary),
            )[-1]
            data = latest_failure.data or {}
            merchant = str(
                data.get("merchant")
                or data.get("merchant_id")
                or latest_failure.actor_id
                or "unknown merchant"
            )
            source = str(data.get("source_domain") or "unknown_source")
            target = str(data.get("target_domain") or "unknown_target")
            amount_cents = _as_int(data.get("amount_cents", 0))
            error = str(data.get("error") or "unknown_failure")
            protocols = protocol_list_label(data.get("accepted_protocols"))
            fail_label = (
                "failure" if len(treasury_failed) == 1 else f"latest of {len(treasury_failed)} failures"
            )
            lines.append(
                f"No-route pressure: R{latest_failure.round_num} {fail_label}: "
                f"{merchant} could not rebalance {_cents_to_dollars(amount_cents)} "
                f"from {source} to {target}; accepted protocols {protocols} had "
                f"no feasible route ({error})."
            )

        if self.result.treasury_posture_summary:
            tightest = min(
                self.result.treasury_posture_summary,
                key=lambda row: float(row.get("min_preferred_ratio", 1.0)),
            )
            lines.append(
                f"Merchant treasury watch: {tightest['merchant']} reached "
                f"{float(tightest.get('min_preferred_ratio', 0)) * 100:.1f}% in preferred "
                f"{tightest['preferred_domain']} with "
                f"{_cents_to_dollars(int(tightest.get('max_preferred_shortfall_cents', 0)))} max shortfall."
            )

        if self.result.trust_summary:
            trust_rows = [
                (name, trust)
                for name, trust in self.result.trust_summary.items()
                if isinstance(trust, dict)
            ]
            if trust_rows:
                trusted = max(trust_rows, key=lambda row: float(row[1].get("avg", 0)))
                fragile = min(trust_rows, key=lambda row: float(row[1].get("avg", 0)))
                lines.append(
                    f"Agent trust anchor: {protocol_display_label(trusted[0])} leads at avg "
                    f"{float(trusted[1].get('avg', 0)):.2f}; {protocol_display_label(fragile[0])} is weakest at "
                    f"{float(fragile[1].get('avg', 0)):.2f}."
                )

        if self.result.agent_memory_log:
            driver_totals: dict[str, float] = {}
            driver_counts: dict[str, int] = {}
            for memory in self.result.agent_memory_log:
                driver = memory.trust_driver or memory.outcome or "unclassified"
                driver_totals[driver] = driver_totals.get(driver, 0.0) + memory.sentiment_delta
                driver_counts[driver] = driver_counts.get(driver, 0) + 1
            drivers = sorted(
                driver_totals,
                key=lambda driver: (
                    -abs(driver_totals[driver]),
                    -driver_counts[driver],
                    driver,
                ),
            )
            if drivers:
                driver = drivers[0]
                lines.append(
                    f"Memory driver: {driver.replace('_', ' ')} produced "
                    f"{driver_counts[driver]} memories with net trust {driver_totals[driver]:+.2f}."
                )

            pressure_memories = [
                memory for memory in self.result.agent_memory_log
                if (
                    memory.ecosystem_pressure > 0
                    or "route_pressure" in (memory.trust_driver or "")
                    or "route pressure" in (memory.reason or "")
                )
            ]
            pressure_buckets = {}
            for memory in pressure_memories:
                proto = (memory.protocol or "unknown").lower()
                route_id = memory.route_id or "unknown_route"
                bucket = pressure_buckets.setdefault(
                    (proto, route_id),
                    {"count": 0, "net": 0.0, "max_pressure": 0.0, "amount": 0},
                )
                bucket["count"] += 1
                bucket["net"] += memory.sentiment_delta
                bucket["max_pressure"] = max(bucket["max_pressure"], memory.ecosystem_pressure)
                bucket["amount"] += memory.amount_cents

            if pressure_buckets:
                (proto, route_id), bucket = sorted(
                    pressure_buckets.items(),
                    key=lambda item: (
                        -abs(float(item[1]["net"])),
                        -int(item[1]["count"]),
                        item[0][0],
                        item[0][1],
                    ),
                )[0]
                count = int(bucket["count"])
                memory_label = "memory" if count == 1 else "memories"
                lines.append(
                    f"Route-pressure memory: {protocol_display_label(proto)} on {route_id} recorded "
                    f"{count} pressure-linked {memory_label}, max pressure "
                    f"{float(bucket['max_pressure']) * 100:.1f}%, net trust "
                    f"{float(bucket['net']):+.2f}, attempt value "
                    f"{_cents_to_dollars(int(bucket['amount']))}."
                )

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

        if route_pressure_rows:
            lines.append("")
            lines.append("Most pressured routes:")
            for route in route_pressure_rows[:5]:
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
                key=lambda item: (item[1].operator_margin_cents, item[0]),
            )
            worst_name, worst_state = states[0]
            best_name, best_state = states[-1]
            if worst_state.operator_margin_cents < 0:
                if worst_name == best_name:
                    lines.append(
                        f"Rail margin watch: {protocol_display_label(worst_name)} is losing "
                        f"{_cents_to_dollars(abs(worst_state.operator_margin_cents))} "
                        f"after {_cents_to_dollars(worst_state.fee_revenue_cents)} revenue and "
                        f"{_cents_to_dollars(worst_state.infrastructure_cost_cents)} infrastructure cost."
                    )
                else:
                    lines.append(
                        f"Rail margin watch: {protocol_display_label(worst_name)} is losing "
                        f"{_cents_to_dollars(abs(worst_state.operator_margin_cents))} "
                        f"after {_cents_to_dollars(worst_state.fee_revenue_cents)} revenue and "
                        f"{_cents_to_dollars(worst_state.infrastructure_cost_cents)} infrastructure cost; "
                        f"{protocol_display_label(best_name)} leads at {_cents_to_dollars(best_state.operator_margin_cents)}."
                    )
            else:
                lines.append(
                    f"Rail margin watch: {protocol_display_label(best_name)} leads at "
                    f"{_cents_to_dollars(best_state.operator_margin_cents)}; lowest margin is "
                    f"{protocol_display_label(worst_name)} at {_cents_to_dollars(worst_state.operator_margin_cents)}."
                )
            for name, state in states:
                lines.append(
                    f"  {protocol_display_label(name)}: margin={_cents_to_dollars(state.operator_margin_cents)}, "
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
            _as_float(route.get("max_capacity_ratio", 0)) >= 1.0
            for route in route_pressure_rows
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
            avg_route_score = pm.get("avg_route_score", 0.0)
            avg_pressure = abs(pm.get("avg_route_pressure_penalty", 0.0))
            avg_sustainability = pm.get("avg_sustainability_bias", 0.0)

            lines = [
                f"Transactions: {txns} ({success} ok, {failed} failed)",
                f"Volume: {_cents_to_dollars(vol)}",
                f"Fees: {_cents_to_dollars(fees)} ({_pct(fees, vol)} of volume)",
                f"Avg execution time: {avg_exec:.3f} ms",
                f"Avg selected-route score: {avg_route_score:.2f}",
                f"Route pressure drag: {avg_pressure:.2f}; sustainability lift: {avg_sustainability:.2f}",
                f"Micropayments (< $1): {micro}",
                f"Success rate: {_pct(success, txns)}",
            ]

            status = "ok"
            if txns == 0:
                status = "empty"
            elif failed > success:
                status = "warn"

            sections.append({
                "title": f"Protocol: {protocol_display_label(proto_name)}",
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
            *[f"  {i+1}. {protocol_display_label(p)} ({_get(p, 'avg_settlement_ms', 0):.3f} ms)" for i, p in enumerate(by_speed)],
            "",
            "Lowest fee ratio:",
            *[f"  {i+1}. {protocol_display_label(p)} ({_pct(_get(p, 'total_fees_cents'), _get(p, 'total_volume_cents'))})" for i, p in enumerate(by_cost)],
            "",
            "Most reliable:",
            *[f"  {i+1}. {protocol_display_label(p)} ({_pct(_get(p, 'successful_transactions'), _get(p, 'total_transactions'))})" for i, p in enumerate(by_reliability)],
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
                f"  {idx}. {protocol_display_label(name)} "
                f"(margin={_cents_to_dollars(state.operator_margin_cents)}, "
                f"volume={_cents_to_dollars(state.gross_volume_cents)})"
            )

        lines.append("")
        lines.append("Best ecosystem pull:")
        for idx, (name, state) in enumerate(by_scale, start=1):
            lines.append(
                f"  {idx}. {protocol_display_label(name)} "
                f"(network_effect={state.network_effect:.2f}, merchants={state.merchant_count})"
            )

        return {"title": "Protocol Economics", "content": "\n".join(lines), "status": "ok"}

    def _route_summary(self) -> dict:
        if not self.result.route_usage_summary:
            return {"title": "Route Usage", "content": "No route usage data available.", "status": "empty"}

        lines = ["Most used settlement routes by reserved principal:"]
        for route, usage_cents in sorted(self.result.route_usage_summary.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"  {route}: {_cents_to_dollars(usage_cents)} reserved")
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
            proto_str = ", ".join(
                f"{protocol_display_label(p)}={c}"
                for p, c in sorted(protos.items(), key=lambda kv: kv[1], reverse=True)
            )
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
                lines.append(f"  {protocol_display_label(p)}: {c} txns ({_pct(c, total_txns)})")

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
                f"  {protocol_display_label(p)}: {count} micropayments ({micro_share} of its txns), "
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
                lines.append(f"  {protocol_display_label(p)}: {reason}")

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
                f"Micropayments: {protocol_display_label(best_micro[0])} — lowest fee ratio among protocols "
                f"that handled sub-$1 transactions ({_pct(_get(best_micro[0], 'total_fees_cents'), _get(best_micro[0], 'total_volume_cents'))})."
            )

        # Best for high-value
        hv_best = min(protos, key=fee_ratio)
        recs.append(
            f"High-value transactions: {protocol_display_label(hv_best)} — lowest overall fee ratio "
            f"({_pct(_get(hv_best, 'total_fees_cents'), _get(hv_best, 'total_volume_cents'))})."
        )

        # Best for speed
        speed_best = min(protos, key=lambda p: _get(p, "avg_settlement_ms", float("inf")))
        recs.append(
            f"Latency-sensitive use cases: {protocol_display_label(speed_best)} — fastest avg settlement "
            f"({_get(speed_best, 'avg_settlement_ms', 0):.3f} ms)."
        )

        # Best for reliability
        rel_best = max(protos, key=success_rate)
        recs.append(
            f"Mission-critical commerce: {protocol_display_label(rel_best)} — highest success rate "
            f"({_pct(_get(rel_best, 'successful_transactions'), _get(rel_best, 'total_transactions'))})."
        )

        scored_routes = [
            tx
            for round_summary in self.result.rounds
            for tx in round_summary.transactions
            if tx.success and tx.route_score_drivers
        ]
        if scored_routes:
            chosen = max(scored_routes, key=lambda tx: tx.route_score)
            positive_drivers = sorted(
                (
                    (name, value)
                    for name, value in chosen.route_score_drivers.items()
                    if name != "total" and value > 0
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            pressure = abs(chosen.route_score_drivers.get("route_pressure_penalty", 0.0))
            driver_text = ", ".join(
                f"{name.replace('_', ' ')} {value:.2f}"
                for name, value in positive_drivers[:3]
            )
            recs.append(
                f"Selected route rationale: {protocol_display_label(chosen.protocol)} on {chosen.route_id} "
                f"scored {chosen.route_score:.2f}; {driver_text or 'no positive drivers'} "
                f"offset route pressure {pressure:.2f}."
            )
            runner_up = chosen.route_score_context.get("runner_up")
            if isinstance(runner_up, dict):
                gap = chosen.route_score - _as_float(runner_up.get("score", 0.0))
                recs.append(
                    f"Nearest route alternative: {protocol_display_label(runner_up.get('protocol', 'unknown'))} "
                    f"on {runner_up.get('route_id', 'unknown route')} trailed by {gap:.2f}; "
                    f"selected route pressure stayed at {pressure:.2f} versus "
                    f"{abs(_as_float(runner_up.get('route_pressure_penalty', 0.0))):.2f}."
                )

        if self.result.ecosystem_summary:
            eco_best = max(
                self.result.ecosystem_summary.items(),
                key=lambda item: item[1].operator_margin_cents,
            )
            recs.append(
                f"Ecosystem operator economics: {protocol_display_label(eco_best[0])} — strongest simulated "
                f"margin at {_cents_to_dollars(eco_best[1].operator_margin_cents)}."
            )

        # Caution flags
        cautions: list[str] = []
        for p in protos:
            sr = success_rate(p)
            if sr < 0.90 and _get(p, "total_transactions", 0) > 0:
                cautions.append(
                    f"  {protocol_display_label(p)}: success rate {_pct(_get(p, 'successful_transactions'), _get(p, 'total_transactions'))} "
                    f"— investigate failure causes before production use."
                )
            fr = fee_ratio(p)
            if fr > 0.05 and _get(p, "total_volume_cents", 0) > 0:
                cautions.append(
                    f"  {protocol_display_label(p)}: fee ratio {_pct(_get(p, 'total_fees_cents'), _get(p, 'total_volume_cents'))} "
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
