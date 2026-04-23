import {
  normalizeAgentMemoryEvent,
  normalizeAgentMemoryEvents,
  normalizeEcosystemSummary,
  normalizeNumberArrayRecord,
  normalizeNumberRecord,
  normalizeProtocolSummaries,
  normalizeRoutePressureSummaries,
  normalizeTreasuryPostureSummaries,
  normalizeWorldEvents,
} from './simStream';
import { simState, type AgentMemoryEvent, type EconomyObservabilityStoreFields, type EconomyWorldEvent, type RoutePressureSummary, type SimEvent, type TreasuryPostureSummary } from './stores/simulation.svelte';
import { timelineMetaItems } from './timelineMetadata';

const completeEvent = {
  type: 'simulation_complete',
  route_pressure_summary: [{
    route_id: 'cdp-base->ap2',
    source_domain: 'cdp-base',
    target_domain: 'ap2',
    primitive: 'settlement',
    protocols: ['cdp', 'ap2'],
    total_usage_cents: 1250,
    max_capacity_ratio: 0.72,
    pressure_rounds: 3,
    last_pressure_level: 'high',
  }],
  treasury_posture_summary: [{
    merchant_id: 'merchant_1',
    merchant: 'Merchant 1',
    preferred_domain: 'cdp-base',
    max_preferred_shortfall_cents: 400,
    min_preferred_ratio: 0.65,
    rebalance_ready_rounds: 2,
    last_preferred_ratio: 0.8,
    last_total_treasury_cents: 10000,
  }],
  agent_memory_log: [{
    type: 'agent_memory',
    round_num: 4,
    agent_id: 'agent_1',
    agent_name: 'Agent 1',
    event_type: 'protocol_experience',
    protocol: 'x402',
    workload_type: 'api_micro',
    sentiment_delta: -0.07,
    trust_before: 0.81,
    trust_after: 0.74,
    outcome: 'route_pressure',
    trust_driver: 'ecosystem_pressure',
    ecosystem_pressure: 0.72,
    amount_cents: 125,
    merchant_id: 'merchant_1',
    merchant_name: 'Merchant 1',
    merchant_reputation: 0.93,
    product_name: 'API call',
    route_id: 'cdp-base->ap2',
    reason: 'route pressure raised settlement risk',
  }],
} satisfies SimEvent;

const observabilityEvent = {
  type: 'simulation_complete',
  protocol_summaries: {
    ap2: {
      protocol: 'ap2',
      total_transactions: 3,
      successful_transactions: 3,
      failed_transactions: 0,
      total_volume_cents: 1250,
      total_fees_cents: 25,
      avg_settlement_ms: 18.2,
      avg_authorization_ms: 0,
      micropayment_count: 1,
    },
  },
  ecosystem_summary: {
    ap2: {
      merchant_count: 2,
      network_effect: 0.7,
      congestion: 0.1,
      operator_margin_cents: 145,
      reliability: 0.97,
      route_mix: {
        'cdp-base->ap2': 3,
      },
    },
  },
  route_usage_summary: {
    'cdp-base->ap2': 1250,
  },
  rail_pnl_history: {
    ap2: [120, 145],
  },
  world_events: [{
    round_num: 5,
    event_type: 'merchant_protocol_mix_changed',
    summary: 'Merchant 1 adopted AP2 from ecosystem evidence',
    actor_id: 'merchant_1',
    protocol: 'ap2',
    data: {
      merchant_id: 'merchant_1',
      merchant: 'Merchant 1',
      action: 'adopted',
      protocol: 'ap2',
      round: 5,
      reason: 'ecosystem_evidence',
      evidence: {
        adoption_score: 0.73,
        route_pressure: 0.2,
        treasury_pressure: 0.1,
      },
    },
  }],
} satisfies SimEvent;

const merchantSwitchEvent = {
  type: 'merchant_switch',
  merchant_id: 'merchant_1',
  merchant: 'Merchant 1',
  action: 'adopted',
  protocol: 'ap2',
  round: 5,
  reason: 'ecosystem_evidence',
  evidence: {
    adoption_score: 0.73,
    route_pressure: 0.2,
    treasury_pressure: 0.1,
  },
} satisfies SimEvent;

const routePressure: RoutePressureSummary[] = normalizeRoutePressureSummaries(completeEvent.route_pressure_summary);
const treasuryPosture: TreasuryPostureSummary[] = normalizeTreasuryPostureSummaries(completeEvent.treasury_posture_summary);
const batchMemories: AgentMemoryEvent[] = normalizeAgentMemoryEvents(completeEvent.agent_memory_log) ?? [];
const singleMemory = requireMemory(normalizeAgentMemoryEvent(completeEvent.agent_memory_log[0] as SimEvent));
const observabilityWorldEvents: EconomyWorldEvent[] = normalizeWorldEvents(observabilityEvent.world_events) ?? [];
const routeTimelineMeta = requireTimelineMeta(timelineMetaItems({
  type: 'world_event',
  event_type: 'route_pressure',
  summary: 'route pressure',
  data: completeEvent.route_pressure_summary[0],
}));
const treasuryTimelineMeta = requireTimelineMeta(timelineMetaItems({
  type: 'world_event',
  event_type: 'treasury_posture',
  summary: 'treasury posture',
  data: completeEvent.treasury_posture_summary[0],
}));
const memoryTimelineMeta = requireTimelineMeta(timelineMetaItems(completeEvent.agent_memory_log[0]));

simState.routePressureSummary = routePressure;
simState.treasuryPostureSummary = treasuryPosture;
simState.agentMemories = [...batchMemories, singleMemory];
simState.metrics = normalizeProtocolSummaries(observabilityEvent.protocol_summaries);
simState.ecosystem = normalizeEcosystemSummary(observabilityEvent.ecosystem_summary);
simState.routeUsage = normalizeNumberRecord(observabilityEvent.route_usage_summary);
simState.railPnlHistory = normalizeNumberArrayRecord(observabilityEvent.rail_pnl_history);
simState.worldEvents = observabilityWorldEvents;
simState.events = [merchantSwitchEvent];

const economyObservabilityState: EconomyObservabilityStoreFields = {
  metrics: simState.metrics,
  ecosystem: simState.ecosystem,
  routeUsage: simState.routeUsage,
  railPnlHistory: simState.railPnlHistory,
  worldEvents: simState.worldEvents,
  events: simState.events,
};

export const streamNormalizationContract = {
  route: {
    route_id: routePressure[0]?.route_id,
    source_domain: routePressure[0]?.source_domain,
    target_domain: routePressure[0]?.target_domain,
    primitive: routePressure[0]?.primitive,
    protocols: routePressure[0]?.protocols,
    total_usage_cents: routePressure[0]?.total_usage_cents,
    max_capacity_ratio: routePressure[0]?.max_capacity_ratio,
    pressure_rounds: routePressure[0]?.pressure_rounds,
    last_pressure_level: routePressure[0]?.last_pressure_level,
  },
  treasury: {
    merchant_id: treasuryPosture[0]?.merchant_id,
    merchant: treasuryPosture[0]?.merchant,
    preferred_domain: treasuryPosture[0]?.preferred_domain,
    max_preferred_shortfall_cents: treasuryPosture[0]?.max_preferred_shortfall_cents,
    min_preferred_ratio: treasuryPosture[0]?.min_preferred_ratio,
    rebalance_ready_rounds: treasuryPosture[0]?.rebalance_ready_rounds,
    last_preferred_ratio: treasuryPosture[0]?.last_preferred_ratio,
    last_total_treasury_cents: treasuryPosture[0]?.last_total_treasury_cents,
  },
  memory: {
    outcome: simState.agentMemories[0]?.outcome,
    trust_driver: simState.agentMemories[0]?.trust_driver,
    ecosystem_pressure: simState.agentMemories[0]?.ecosystem_pressure,
    merchant_reputation: simState.agentMemories[0]?.merchant_reputation,
    route_id: simState.agentMemories[0]?.route_id,
  },
  timeline: {
    route: requireTimelineLabels(routeTimelineMeta, [
      'from: cdp-base',
      'to: ap2',
      'mode: settlement',
      'route: cdp-base->ap2',
      'pressure: high',
      'capacity: 72.0%',
    ]),
    treasury: requireTimelineLabels(treasuryTimelineMeta, [
      'merchant: Merchant 1',
      'preferred: 80.0%',
      'shortfall: $4.00',
    ]),
    memory: requireTimelineLabels(memoryTimelineMeta, [
      'merchant: Merchant 1',
      'route: cdp-base->ap2',
      'driver: ecosystem pressure',
      'outcome: route pressure',
      'stress: 72.0%',
    ]),
  },
  observability: requireEconomyObservabilityContract({
    routeLedgerValue: economyObservabilityState.routeUsage['cdp-base->ap2'] ?? 0,
    routeMixAttempts: economyObservabilityState.ecosystem.ap2?.route_mix?.['cdp-base->ap2'] ?? 0,
    railMarginSnapshots: economyObservabilityState.railPnlHistory.ap2 ?? [],
    merchantSwitchType: economyObservabilityState.events[0]?.type,
    worldSwitchType: economyObservabilityState.worldEvents[0]?.event_type,
    switchReason: economyObservabilityState.worldEvents[0]?.data?.reason,
    metricsProtocol: economyObservabilityState.metrics[0]?.protocol,
  }),
};

type EconomyObservabilityContract = {
  routeLedgerValue: number;
  routeMixAttempts: number;
  railMarginSnapshots: number[];
  merchantSwitchType?: unknown;
  worldSwitchType?: unknown;
  switchReason?: unknown;
  metricsProtocol?: unknown;
};

function requireMemory(memory: AgentMemoryEvent | null): AgentMemoryEvent {
  if (!memory) throw new Error('agent memory stream contract did not normalize');
  return memory;
}

function requireTimelineMeta(meta: string[]): string[] {
  if (meta.length === 0) throw new Error('timeline metadata contract did not render');
  return meta;
}

function requireTimelineLabels(meta: string[], expected: string[]): string[] {
  const missing = expected.filter((label) => !meta.includes(label));
  if (missing.length > 0) {
    throw new Error(`timeline metadata contract missing labels: ${missing.join(', ')}`);
  }
  return meta;
}

function requireEconomyObservabilityContract(contract: EconomyObservabilityContract): EconomyObservabilityContract {
  if (contract.routeLedgerValue <= 0) {
    throw new Error('economy observability contract missing route ledger value');
  }
  if (contract.routeMixAttempts <= 0) {
    throw new Error('economy observability contract missing route mix attempts');
  }
  if (contract.railMarginSnapshots.length < 2) {
    throw new Error('economy observability contract missing rail margin history');
  }
  if (contract.merchantSwitchType !== 'merchant_switch') {
    throw new Error('economy observability contract missing merchant switch event');
  }
  if (contract.worldSwitchType !== 'merchant_protocol_mix_changed') {
    throw new Error('economy observability contract missing merchant switch world event');
  }
  if (contract.switchReason !== 'ecosystem_evidence') {
    throw new Error('economy observability contract missing switch reason evidence');
  }
  if (contract.metricsProtocol !== 'ap2') {
    throw new Error('economy observability contract missing protocol metrics');
  }
  return contract;
}
