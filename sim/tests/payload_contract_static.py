"""Static drift check for the simulation payload documentation.

Run from the repository root:

    python3 sim/tests/payload_contract_static.py
"""

from __future__ import annotations

import re
import sys
from dataclasses import fields
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sim"))

from sim.types import (  # noqa: E402
    AgentMemoryEvent,
    EconomyWorldEvent,
    RoundSummary,
    SimulationResult,
)


def code_tokens(text: str) -> set[str]:
    return set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", text))


def has_phrase(text: str, phrase: str) -> bool:
    return re.search(r"\s+".join(re.escape(part) for part in phrase.split()), text) is not None


def assert_no_payload_doc_drift() -> None:
    agents_doc_path = ROOT / "AGENTS.md"
    agents_doc = agents_doc_path.read_text() if agents_doc_path.exists() else ""
    contract = (ROOT / "docs/simulation-payload-contract.md").read_text()
    architecture = (ROOT / "docs/simulation-architecture.md").read_text()
    engine_source = (ROOT / "sim/sim/engine.py").read_text()
    helper_source = (ROOT / "web/src/lib/simStream.ts").read_text()
    stream_contract_source = (ROOT / "web/src/lib/simStream.contract.ts").read_text()
    timeline_source = (ROOT / "web/src/lib/components/Timeline.svelte").read_text()
    observability_source = (ROOT / "web/src/lib/components/EconomyObservability.svelte").read_text()
    workbench_source = (ROOT / "web/src/routes/sim/new/+page.svelte").read_text()
    store_source = (ROOT / "web/src/lib/stores/simulation.svelte.ts").read_text()
    report_source = (ROOT / "sim/sim/report.py").read_text()
    tokens = code_tokens(contract)

    assert "docs/simulation-payload-contract.md" in architecture

    required_intent_phrases = {
        "AGENTS.md": (
            (agents_doc, "Meridian product contract"),
            (agents_doc, "agents initiate transactions"),
            (agents_doc, "visualize the ecosystem economy"),
            (agents_doc, "Do not ask the user what phase comes next"),
            (agents_doc, "do not pause for phase approval"),
        ),
        "docs/simulation-architecture.md": (
            (architecture, "Product Contract"),
            (architecture, "agents initiating transactions across payment protocols"),
            (architecture, "ecosystem economy"),
            (architecture, "reference rails for realism"),
            (architecture, "SDK console or funding dashboard"),
            (architecture, "workbench economy observability surface"),
            (architecture, "only stop for a real blocker"),
        ),
        "docs/simulation-payload-contract.md": (
            (contract, "Simulation Intent"),
            (contract, "Payloads describe an ecosystem economy"),
            (contract, "Agent transaction attempts"),
            (contract, "frontend to visualize why the economy moved"),
            (contract, "not crowd out the agent/economy story"),
            (contract, "Economy Observability Surface"),
            (contract, "Route Ledger"),
            (contract, "Reserved Principal"),
            (contract, "Merchant Adaptation"),
            (contract, "Protocol Changes"),
            (contract, "Display edge rules"),
            (contract, "non-finite display numbers"),
        ),
    }
    missing_intent_phrases = sorted(
        f"{doc_name}: {phrase}"
        for doc_name, checks in required_intent_phrases.items()
        for source, phrase in checks
        if not has_phrase(source, phrase)
    )
    assert missing_intent_phrases == [], (
        "simulation intent/autonomy guidance missing: "
        f"{', '.join(missing_intent_phrases)}"
    )

    for payload_type in (
        AgentMemoryEvent,
        EconomyWorldEvent,
        RoundSummary,
        SimulationResult,
    ):
        assert payload_type.__name__ in tokens
        missing_fields = sorted(
            field.name for field in fields(payload_type)
            if field.name not in tokens
        )
        assert missing_fields == [], (
            f"{payload_type.__name__} fields missing from payload contract: "
            f"{', '.join(missing_fields)}"
        )

    exported_helpers = set(
        re.findall(
            r"^export function ([A-Za-z_][A-Za-z0-9_]*)",
            helper_source,
            re.MULTILINE,
        )
    )
    assert exported_helpers
    missing_helpers = sorted(exported_helpers - tokens)
    assert missing_helpers == [], (
        "simStream exports missing from payload contract: "
        f"{', '.join(missing_helpers)}"
    )

    stream_events = {
        "setup",
        "simulation_start",
        "round_complete",
        "simulation_complete",
        "purchase",
        "purchase_failed",
        "route_execution",
        "balance_update",
        "agent_memory",
        "trust_snapshot",
        "world_event",
        "route_pressure",
        "treasury_rebalance",
        "treasury_rebalance_failed",
        "treasury_posture",
        "social_memory_diffusion",
        "merchant_switch",
        "agent_preference_shift",
        "rail_pnl_update",
        "market_snapshot",
    }
    missing_events = sorted(stream_events - tokens)
    assert missing_events == [], (
        "stream events missing from payload contract: "
        f"{', '.join(missing_events)}"
    )

    required_phrases = (
        "ref/mirofish",
        "ref/deps/*",
        "OASIS",
        "CAMEL",
        "reference rails",
        "unknown fields",
        "route usage fields are cents",
        "route mix fields are attempt counts",
        "rail P&L fields are margin-cent snapshots",
        "python3 sim/tests/payload_contract_static.py",
    )
    missing_phrases = sorted(
        phrase for phrase in required_phrases
        if phrase not in contract
    )
    assert missing_phrases == [], (
        "reference/maintenance guidance missing from payload contract: "
        f"{', '.join(missing_phrases)}"
    )

    merchant_switch_doc_tokens = {
        "merchant_protocol_mix_changed",
        "merchant_id",
        "merchant",
        "action",
        "protocol",
        "round",
        "reason",
        "evidence",
        "ecosystem_evidence",
        "rail_economics",
        "adoption_score",
        "removal_risk",
        "avg_trust",
        "recent_memory_signal",
        "route_pressure",
        "treasury_pressure",
        "serves_preferred_domain",
        "reliability",
        "operator_margin_cents",
    }
    missing_switch_doc_tokens = sorted(merchant_switch_doc_tokens - tokens)
    assert missing_switch_doc_tokens == [], (
        "merchant switch evidence fields missing from payload contract: "
        f"{', '.join(missing_switch_doc_tokens)}"
    )

    route_score_doc_tokens = {
        "route_score",
        "route_score_drivers",
        "route_score_context",
        "avg_route_score",
        "avg_route_pressure_penalty",
        "avg_sustainability_bias",
        "route_score_pressure_drag",
        "route_score_sustainability_lift",
    }
    missing_route_score_doc_tokens = sorted(route_score_doc_tokens - tokens)
    assert missing_route_score_doc_tokens == [], (
        "route-score rationale fields missing from payload contract: "
        f"{', '.join(missing_route_score_doc_tokens)}"
    )

    required_route_score_phrases = {
        "architecture route-score section": (
            architecture,
            "Route-Score Rationale",
        ),
        "architecture buyer-to-economy rationale": (
            architecture,
            "bridge between one agent transaction and the protocol economy",
        ),
        "architecture self-sustainability rationale": (
            architecture,
            "self-sustainability bias",
        ),
        "architecture protocol evolution rationale": (
            architecture,
            "protocols gain or lose usage",
        ),
        "payload route-score rationale": (
            contract,
            "Route-score rationale belongs beside those source fields",
        ),
        "payload selected buyer route": (
            contract,
            "explain the selected buyer route",
        ),
        "payload protocol-level route evidence": (
            contract,
            "protocol-level route evidence",
        ),
    }
    missing_route_score_phrases = sorted(
        label for label, (source, phrase) in required_route_score_phrases.items()
        if not has_phrase(source, phrase)
    )
    assert missing_route_score_phrases == [], (
        "route-score rationale docs missing: "
        f"{', '.join(missing_route_score_phrases)}"
    )

    required_route_score_sources = {
        "engine route score selected option": (
            engine_source,
            'best_option["route_score"]',
        ),
        "engine route score drivers selected option": (
            engine_source,
            'best_option["route_score_drivers"]',
        ),
        "engine route score context selected option": (
            engine_source,
            'best_option["route_score_context"]',
        ),
        "engine average route score summary": (
            engine_source,
            '"avg_route_score"',
        ),
        "engine average pressure penalty summary": (
            engine_source,
            '"avg_route_pressure_penalty"',
        ),
        "engine average sustainability bias summary": (
            engine_source,
            '"avg_sustainability_bias"',
        ),
        "engine merchant pressure drag evidence": (
            engine_source,
            '"route_score_pressure_drag"',
        ),
        "engine merchant sustainability lift evidence": (
            engine_source,
            '"route_score_sustainability_lift"',
        ),
        "report merchant route-score readout": (
            report_source,
            "Route-score merchant changes:",
        ),
    }
    missing_route_score_sources = sorted(
        label for label, (source, phrase) in required_route_score_sources.items()
        if phrase not in source
    )
    assert missing_route_score_sources == [], (
        "route-score rationale source anchors missing: "
        f"{', '.join(missing_route_score_sources)}"
    )

    merchant_switch_source_literals = {
        '"merchant_protocol_mix_changed"',
        '"reason"',
        '"evidence"',
        '"ecosystem_evidence"',
        '"rail_economics"',
        '"adoption_score"',
        '"removal_risk"',
        '"avg_trust"',
        '"recent_memory_signal"',
        '"route_pressure"',
        '"treasury_pressure"',
        '"serves_preferred_domain"',
        '"reliability"',
        '"operator_margin_cents"',
    }
    missing_switch_source_literals = sorted(
        literal for literal in merchant_switch_source_literals
        if literal not in engine_source
    )
    assert missing_switch_source_literals == [], (
        "merchant switch evidence fields missing from engine payload: "
        f"{', '.join(missing_switch_source_literals)}"
    )

    assert "timelineMetaItems(evt)" in timeline_source
    assert "import { timelineMetaItems" in stream_contract_source
    required_timeline_labels = (
        "from: cdp-base",
        "to: ap2",
        "mode: settlement",
        "route: cdp-base->ap2",
        "pressure: high",
        "capacity: 72.0%",
        "merchant: Merchant 1",
        "preferred: 80.0%",
        "shortfall: $4.00",
        "driver: ecosystem pressure",
        "outcome: route pressure",
        "stress: 72.0%",
    )
    missing_timeline_labels = sorted(
        label for label in required_timeline_labels
        if label not in stream_contract_source
    )
    assert missing_timeline_labels == [], (
        "timeline metadata labels missing from stream contract: "
        f"{', '.join(missing_timeline_labels)}"
    )

    required_accounting_sources = {
        "routeUsage store": (store_source, "routeUsage = $state<Record<string, number>>"),
        "railPnlHistory store": (store_source, "railPnlHistory = $state<Record<string, number[]>>"),
        "route_mix store": (store_source, "route_mix?: Record<string, number>"),
        "route usage report label": (report_source, "reserved principal"),
        "route usage report money formatting": (report_source, "_cents_to_dollars(usage_cents)"),
    }
    missing_accounting_sources = sorted(
        label for label, (source, phrase) in required_accounting_sources.items()
        if phrase not in source
    )
    assert missing_accounting_sources == [], (
        "accounting unit static anchors missing: "
        f"{', '.join(missing_accounting_sources)}"
    )

    required_observability_sources = {
        "store observability field contract": (
            store_source,
            "export interface EconomyObservabilityStoreFields",
        ),
        "store observability metrics field": (
            store_source,
            "metrics: ProtoMetrics[]",
        ),
        "store observability route usage field": (
            store_source,
            "routeUsage: Record<string, number>",
        ),
        "store observability rail pnl field": (
            store_source,
            "railPnlHistory: Record<string, number[]>",
        ),
        "workbench observability import": (
            workbench_source,
            "import EconomyObservability from '$lib/components/EconomyObservability.svelte'",
        ),
        "workbench observability render": (
            workbench_source,
            "<EconomyObservability",
        ),
        "workbench observability route prop": (
            workbench_source,
            "routeUsage={simState.routeUsage}",
        ),
        "workbench observability rail prop": (
            workbench_source,
            "railPnlHistory={simState.railPnlHistory}",
        ),
        "workbench route usage normalizer": (
            workbench_source,
            "simState.routeUsage = normalizeNumberRecord(ev.route_usage_summary)",
        ),
        "workbench rail pnl normalizer": (
            workbench_source,
            "simState.railPnlHistory = normalizeNumberArrayRecord(ev.rail_pnl_history)",
        ),
        "observability route ledger label": (
            observability_source,
            "Route Ledger",
        ),
        "observability reserved principal label": (
            observability_source,
            "Reserved Principal",
        ),
        "observability route mix attempts label": (
            observability_source,
            "route-mix attempts",
        ),
        "observability rail pnl label": (
            observability_source,
            "Rail P&amp;L",
        ),
        "observability margin drift label": (
            observability_source,
            "Margin Drift",
        ),
        "observability merchant adaptation label": (
            observability_source,
            "Merchant Adaptation",
        ),
        "observability protocol changes label": (
            observability_source,
            "Protocol Changes",
        ),
        "observability direct merchant switch source": (
            observability_source,
            "event.type === 'merchant_switch'",
        ),
        "observability world merchant switch source": (
            observability_source,
            "merchant_protocol_mix_changed",
        ),
        "observability route principal clamp": (
            observability_source,
            "nonNegativeNumber(usage[route])",
        ),
        "observability route mix clamp": (
            observability_source,
            "wholeNonNegative(count)",
        ),
        "observability finite rail history": (
            observability_source,
            "finiteValues(historyByProtocol[protocol])",
        ),
        "stream contract observability helper": (
            stream_contract_source,
            "requireEconomyObservabilityContract",
        ),
        "stream contract observability store type": (
            stream_contract_source,
            "EconomyObservabilityStoreFields",
        ),
        "stream contract observability route ledger value": (
            stream_contract_source,
            "routeLedgerValue",
        ),
        "stream contract observability merchant evidence": (
            stream_contract_source,
            "switchReason",
        ),
        "stream contract partial observability fixture": (
            stream_contract_source,
            "partialObservabilityEvent",
        ),
        "stream contract route ledger clamp": (
            stream_contract_source,
            "nonNegativeRouteLedgerValue",
        ),
        "stream contract route mix clamp": (
            stream_contract_source,
            "nonNegativeRouteMixAttempts",
        ),
        "stream contract rail loss preserved": (
            stream_contract_source,
            "railLossSnapshot",
        ),
    }
    missing_observability_sources = sorted(
        label for label, (source, phrase) in required_observability_sources.items()
        if phrase not in source
    )
    assert missing_observability_sources == [], (
        "economy observability static anchors missing: "
        f"{', '.join(missing_observability_sources)}"
    )


if __name__ == "__main__":
    assert_no_payload_doc_drift()
    print("simulation payload contract ok")
