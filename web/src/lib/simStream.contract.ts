import {
  buildNoRoutePressureRows,
  buildRoutePressureRows,
  formatRoutePressureLabel,
} from './routePressureDisplay';
import { routeScoreDriverDisplay } from './routeScoreDrivers';
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
      avg_route_score: 1.25,
      avg_route_pressure_penalty: -0.2,
      avg_sustainability_bias: 0.08,
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

const partialObservabilityEvent = {
  type: 'simulation_complete',
  protocol_summaries: {
    ap2: {
      protocol: 'ap2',
      avg_route_score: '1.4',
    },
    cdp: {
      protocol: 'cdp',
      avg_route_score: 'NaN',
      avg_route_pressure_penalty: Infinity,
      avg_sustainability_bias: '',
    },
  },
  ecosystem_summary: {
    ap2: {
      operator_margin_cents: -25,
      route_mix: {
        'cdp-base->ap2': '-4',
      },
    },
  },
  route_usage_summary: {
    'cdp-base->ap2': '-500',
  },
  rail_pnl_history: {
    ap2: [120, 'bad', -25],
  },
} satisfies SimEvent;

const mixedShapeObservabilityEvent = {
  type: 'simulation_complete',
  protocol_summaries: [{
    protocol: 'x402',
    total_transactions: '2',
    successful_transactions: '1',
    failed_transactions: '1',
    total_volume_cents: '900',
    total_fees_cents: '9',
    avg_settlement_ms: '4.5',
    avg_authorization_ms: '1.2',
    micropayment_count: '2',
  }],
  ecosystem_summary: [{
    protocol: 'x402',
    merchant_count: '1',
    network_effect: '0.4',
    congestion: 'bad',
    operator_margin_cents: '35',
    reliability: '0.75',
    route_mix: {
      'ap2->x402': '2',
    },
  }],
  route_usage_summary: [{
    route_id: 'ap2->x402',
    reserved_cents: '900',
  }],
  rail_pnl_history: [{
    protocol: 'x402',
    history: ['10', 'bad', '35'],
  }],
} satisfies SimEvent;

const keyedSummaryEvent = {
  type: 'simulation_complete',
  route_pressure_summary: {
    'ap2->x402': {
      source_domain: 'ap2',
      target_domain: 'x402',
      primitive: 'authorization',
      protocols: ['ap2', 'x402'],
      total_usage_cents: '900',
      max_capacity_ratio: '0.66',
      pressure_rounds: '2',
      last_pressure_level: 'medium',
    },
  },
  treasury_posture_summary: {
    merchant_2: {
      merchant: 'Merchant 2',
      preferred_domain: 'x402',
      max_preferred_shortfall_cents: '250',
      min_preferred_ratio: '0.55',
      rebalance_ready_rounds: '1',
      last_preferred_ratio: '0.7',
      last_total_treasury_cents: '8000',
    },
  },
} satisfies SimEvent;

const treasuryFailureEvidenceEvent = {
  type: 'simulation_complete',
  route_pressure_summary: [{
    route_id: 'treasury_rebalance_unroutable:tempo_usd->base_usdc',
    source_domain: 'tempo_usd',
    target_domain: 'base_usdc',
    primitive: 'treasury_rebalance',
    accepted_protocols: ['mpp'],
    amount_cents: '36000',
    capacity_ratio: '1.06',
    pressure_level: 'critical',
    error: 'no_feasible_rebalance_route',
    merchant_id: 'merchant_test',
    merchant: 'Merchant Test',
    failure_count: '2',
  }],
  world_events: [{
    round_num: 4,
    event_type: 'treasury_rebalance_failed',
    summary: 'Merchant Test could not find a feasible treasury route.',
    actor_id: 'merchant_test',
    data: {
      merchant_id: 'merchant_test',
      merchant: 'Merchant Test',
      amount_cents: '12000',
      source_domain: 'tempo_usd',
      target_domain: 'base_usdc',
      accepted_protocols: ['mpp'],
      error: 'no_feasible_rebalance_route',
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

const partialRouteUsage = normalizeNumberRecord(partialObservabilityEvent.route_usage_summary);
const partialMetrics = normalizeProtocolSummaries(partialObservabilityEvent.protocol_summaries);
const partialEcosystem = normalizeEcosystemSummary(partialObservabilityEvent.ecosystem_summary);
const partialRailPnlHistory = normalizeNumberArrayRecord(partialObservabilityEvent.rail_pnl_history);
const mixedMetrics = normalizeProtocolSummaries(mixedShapeObservabilityEvent.protocol_summaries);
const mixedEcosystem = normalizeEcosystemSummary(mixedShapeObservabilityEvent.ecosystem_summary);
const mixedRouteUsage = normalizeNumberRecord(mixedShapeObservabilityEvent.route_usage_summary);
const mixedRailPnlHistory = normalizeNumberArrayRecord(mixedShapeObservabilityEvent.rail_pnl_history);
const keyedRoutePressure = normalizeRoutePressureSummaries(keyedSummaryEvent.route_pressure_summary);
const keyedTreasuryPosture = normalizeTreasuryPostureSummaries(keyedSummaryEvent.treasury_posture_summary);
const treasuryUnroutablePressure = normalizeRoutePressureSummaries(treasuryFailureEvidenceEvent.route_pressure_summary);
const treasuryFailureWorldEvents: EconomyWorldEvent[] = normalizeWorldEvents(treasuryFailureEvidenceEvent.world_events) ?? [];
const economyObservabilityState: EconomyObservabilityStoreFields = {
  metrics: simState.metrics,
  ecosystem: simState.ecosystem,
  routeUsage: simState.routeUsage,
  railPnlHistory: simState.railPnlHistory,
  worldEvents: simState.worldEvents,
  events: simState.events,
};
const routePressureDisplayRows = buildRoutePressureRows([
  {
    route_id: 'ordinary-high-capacity',
    source_domain: 'ap2',
    target_domain: 'x402',
    primitive: 'settlement',
    protocols: ['ap2'],
    total_usage_cents: 25000,
    max_capacity_ratio: 1.4,
    pressure_rounds: 5,
    last_pressure_level: 'elevated',
  },
  {
    route_id: 'treasury_rebalance_unroutable:tempo_usd->base_usdc',
    source_domain: 'tempo_usd',
    target_domain: 'base_usdc',
    primitive: 'treasury_rebalance',
    protocols: ['mpp'],
    total_usage_cents: 12000,
    max_capacity_ratio: 0.8,
    pressure_rounds: 2,
    last_pressure_level: 'critical',
    reason: 'no_feasible_rebalance_route',
    merchant: 'Merchant Test',
    failure_count: 2,
  },
  {
    route_id: 'ordinary-failed-route',
    source_domain: 'cdp-base',
    target_domain: 'ap2',
    primitive: 'settlement',
    protocols: ['cdp'],
    total_usage_cents: 4000,
    max_capacity_ratio: 0.55,
    pressure_rounds: 1,
    last_pressure_level: 'medium',
    failure_count: 1,
  },
]);
const noRoutePressureRows = buildNoRoutePressureRows(routePressureDisplayRows.map((row) => ({
  route_id: row.route,
  source_domain: row.domains.split(' to ')[0] ?? 'unknown',
  target_domain: row.domains.split(' to ')[1] ?? 'unknown',
  primitive: 'display_contract',
  protocols: row.protocols,
  total_usage_cents: row.usageCents,
  max_capacity_ratio: row.capacityRatio,
  pressure_rounds: row.pressureRounds,
  last_pressure_level: row.level,
  reason: row.reason,
  merchant: row.merchant,
  failure_count: row.failureCount ?? undefined,
})));

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
    metricsRouteScore: economyObservabilityState.metrics[0]?.avg_route_score,
    metricsPressureDrag: economyObservabilityState.metrics[0]?.avg_route_pressure_penalty,
    metricsSustainabilityLift: economyObservabilityState.metrics[0]?.avg_sustainability_bias,
    partialRouteScoreDriverText: routeScoreDriverDisplay('1.4', undefined, undefined)?.text,
    nonFiniteRouteScoreDriverText: routeScoreDriverDisplay('NaN', Infinity, '')?.text,
    nonFiniteRouteScoreDriverHasFiniteValue: routeScoreDriverDisplay('NaN', Infinity, '')?.hasFiniteValue,
    normalizedPartialRouteScore: partialMetrics.find((metric) => metric.protocol === 'ap2')?.avg_route_score,
    normalizedNonFiniteRouteScore: partialMetrics.find((metric) => metric.protocol === 'cdp')?.avg_route_score,
    nonNegativeRouteLedgerValue: Math.max(0, partialRouteUsage['cdp-base->ap2'] ?? 0),
    nonNegativeRouteMixAttempts: Math.max(0, Math.trunc(partialEcosystem.ap2?.route_mix?.['cdp-base->ap2'] ?? 0)),
    railLossSnapshot: partialRailPnlHistory.ap2?.slice(-1)[0],
    mixedMetricsProtocol: mixedMetrics[0]?.protocol,
    mixedRouteUsageValue: mixedRouteUsage['ap2->x402'],
    mixedRouteMixAttempts: mixedEcosystem.x402?.route_mix?.['ap2->x402'],
    mixedRailLossSnapshot: mixedRailPnlHistory.x402?.slice(-1)[0],
    keyedRoutePressureId: keyedRoutePressure[0]?.route_id,
    keyedTreasuryMerchantId: keyedTreasuryPosture[0]?.merchant_id,
    treasuryFailureType: treasuryFailureWorldEvents[0]?.event_type,
    treasuryFailureError: treasuryFailureWorldEvents[0]?.data?.error,
    treasuryFailureAcceptedProtocol: Array.isArray(treasuryFailureWorldEvents[0]?.data?.accepted_protocols)
      ? treasuryFailureWorldEvents[0]?.data?.accepted_protocols[0]
      : undefined,
    unroutableRouteId: treasuryUnroutablePressure[0]?.route_id,
    unroutableUsageCents: treasuryUnroutablePressure[0]?.total_usage_cents,
    unroutableCapacityRatio: treasuryUnroutablePressure[0]?.max_capacity_ratio,
    unroutablePressureLevel: treasuryUnroutablePressure[0]?.last_pressure_level,
    unroutableReason: treasuryUnroutablePressure[0]?.reason,
    unroutableFailureCount: treasuryUnroutablePressure[0]?.failure_count,
    unroutableAcceptedProtocol: treasuryUnroutablePressure[0]?.protocols[0],
  }),
  routePressureDisplay: requireRoutePressureDisplayContract({
    firstRoute: routePressureDisplayRows[0]?.route,
    firstReason: routePressureDisplayRows[0]?.reason,
    firstLabel: formatRoutePressureLabel(routePressureDisplayRows[0]?.reason ?? ''),
    firstDomains: routePressureDisplayRows[0]?.domains,
    firstProtocol: routePressureDisplayRows[0]?.protocols[0],
    firstFundingContext: routePressureDisplayRows[0]?.fundingContext,
    firstTreasuryNoRoute: routePressureDisplayRows[0]?.isTreasuryNoRoute,
    noRouteRoutes: noRoutePressureRows.map((row) => row.route),
    noRouteReasons: noRoutePressureRows.map((row) => row.reason),
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
  metricsRouteScore?: unknown;
  metricsPressureDrag?: unknown;
  metricsSustainabilityLift?: unknown;
  partialRouteScoreDriverText?: unknown;
  nonFiniteRouteScoreDriverText?: unknown;
  nonFiniteRouteScoreDriverHasFiniteValue?: unknown;
  normalizedPartialRouteScore?: unknown;
  normalizedNonFiniteRouteScore?: unknown;
  nonNegativeRouteLedgerValue: number;
  nonNegativeRouteMixAttempts: number;
  railLossSnapshot?: unknown;
  mixedMetricsProtocol?: unknown;
  mixedRouteUsageValue?: unknown;
  mixedRouteMixAttempts?: unknown;
  mixedRailLossSnapshot?: unknown;
  keyedRoutePressureId?: unknown;
  keyedTreasuryMerchantId?: unknown;
  treasuryFailureType?: unknown;
  treasuryFailureError?: unknown;
  treasuryFailureAcceptedProtocol?: unknown;
  unroutableRouteId?: unknown;
  unroutableUsageCents?: unknown;
  unroutableCapacityRatio?: unknown;
  unroutablePressureLevel?: unknown;
  unroutableReason?: unknown;
  unroutableFailureCount?: unknown;
  unroutableAcceptedProtocol?: unknown;
};

type RoutePressureDisplayContract = {
  firstRoute?: unknown;
  firstReason?: unknown;
  firstLabel: string;
  firstDomains?: unknown;
  firstProtocol?: unknown;
  firstFundingContext?: unknown;
  firstTreasuryNoRoute?: unknown;
  noRouteRoutes: string[];
  noRouteReasons: (string | null)[];
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
  if (contract.metricsRouteScore !== 1.25) {
    throw new Error('economy observability contract missing selected route score');
  }
  if (contract.metricsPressureDrag !== -0.2) {
    throw new Error('economy observability contract missing route pressure score driver');
  }
  if (contract.metricsSustainabilityLift !== 0.08) {
    throw new Error('economy observability contract missing sustainability score driver');
  }
  if (contract.partialRouteScoreDriverText !== 'score 1.40 · pressure n/a · sustain n/a') {
    throw new Error('economy observability contract failed partial route score driver display');
  }
  if (contract.nonFiniteRouteScoreDriverText !== 'score n/a · pressure n/a · sustain n/a') {
    throw new Error('economy observability contract failed non-finite route score driver display');
  }
  if (contract.nonFiniteRouteScoreDriverHasFiniteValue !== false) {
    throw new Error('economy observability contract should mark non-finite route score drivers as unavailable');
  }
  if (contract.normalizedPartialRouteScore !== 1.4) {
    throw new Error('economy observability contract failed partial route score normalization');
  }
  if (contract.normalizedNonFiniteRouteScore !== 0) {
    throw new Error('economy observability contract failed non-finite route score normalization');
  }
  if (contract.nonNegativeRouteLedgerValue !== 0) {
    throw new Error('economy observability contract failed reserved principal clamp');
  }
  if (contract.nonNegativeRouteMixAttempts !== 0) {
    throw new Error('economy observability contract failed route mix attempt clamp');
  }
  if (contract.railLossSnapshot !== -25) {
    throw new Error('economy observability contract should preserve negative rail margin');
  }
  if (contract.mixedMetricsProtocol !== 'x402') {
    throw new Error('economy observability contract failed mixed protocol summaries');
  }
  if (contract.mixedRouteUsageValue !== 900) {
    throw new Error('economy observability contract failed mixed route usage');
  }
  if (contract.mixedRouteMixAttempts !== 2) {
    throw new Error('economy observability contract failed mixed route mix');
  }
  if (contract.mixedRailLossSnapshot !== 35) {
    throw new Error('economy observability contract failed mixed rail history');
  }
  if (contract.keyedRoutePressureId !== 'ap2->x402') {
    throw new Error('economy observability contract failed keyed route pressure summary');
  }
  if (contract.keyedTreasuryMerchantId !== 'merchant_2') {
    throw new Error('economy observability contract failed keyed treasury posture summary');
  }
  if (contract.treasuryFailureType !== 'treasury_rebalance_failed') {
    throw new Error('economy observability contract failed treasury rebalance failure event');
  }
  if (contract.treasuryFailureError !== 'no_feasible_rebalance_route') {
    throw new Error('economy observability contract failed treasury rebalance failure evidence');
  }
  if (contract.treasuryFailureAcceptedProtocol !== 'mpp') {
    throw new Error('economy observability contract failed treasury failure accepted protocols');
  }
  if (contract.unroutableRouteId !== 'treasury_rebalance_unroutable:tempo_usd->base_usdc') {
    throw new Error('economy observability contract failed unroutable route id');
  }
  if (contract.unroutableUsageCents !== 36000) {
    throw new Error('economy observability contract failed unroutable usage alias');
  }
  if (contract.unroutableCapacityRatio !== 1.06) {
    throw new Error('economy observability contract failed unroutable capacity alias');
  }
  if (contract.unroutablePressureLevel !== 'critical') {
    throw new Error('economy observability contract failed unroutable pressure alias');
  }
  if (contract.unroutableReason !== 'no_feasible_rebalance_route') {
    throw new Error('economy observability contract failed unroutable reason evidence');
  }
  if (contract.unroutableFailureCount !== 2) {
    throw new Error('economy observability contract failed unroutable failure count');
  }
  if (contract.unroutableAcceptedProtocol !== 'mpp') {
    throw new Error('economy observability contract failed unroutable accepted protocol alias');
  }
  return contract;
}

function requireRoutePressureDisplayContract(contract: RoutePressureDisplayContract): RoutePressureDisplayContract {
  if (contract.firstRoute !== 'treasury_rebalance_unroutable:tempo_usd->base_usdc') {
    throw new Error('route pressure display contract failed no-route ordering');
  }
  if (contract.firstReason !== 'no_feasible_rebalance_route') {
    throw new Error('route pressure display contract failed no-route reason');
  }
  if (contract.firstLabel !== 'no feasible rebalance route') {
    throw new Error('route pressure display contract failed label formatting');
  }
  if (contract.firstDomains !== 'tempo_usd to base_usdc') {
    throw new Error('route pressure display contract failed domain label');
  }
  if (contract.firstProtocol !== 'mpp') {
    throw new Error('route pressure display contract failed protocol label');
  }
  if (contract.firstTreasuryNoRoute !== true) {
    throw new Error('route pressure display contract failed treasury no-route flag');
  }
  if (contract.firstFundingContext !== 'treasury rebalance · 12000 cents · tempo_usd to base_usdc · via mpp · 2 failed · Merchant Test') {
    throw new Error('route pressure display contract failed funding context');
  }
  if (!contract.noRouteRoutes.includes('treasury_rebalance_unroutable:tempo_usd->base_usdc')) {
    throw new Error('route pressure display contract dropped no-route treasury evidence');
  }
  if (!contract.noRouteRoutes.includes('ordinary-failed-route')) {
    throw new Error('route pressure display contract dropped failed pressure evidence');
  }
  if (contract.noRouteRoutes.includes('ordinary-high-capacity')) {
    throw new Error('route pressure display contract included pressure without no-route or failure evidence');
  }
  if (!contract.noRouteReasons.includes('no_feasible_rebalance_route')) {
    throw new Error('route pressure display contract lost no-route reason in filtered rows');
  }
  return contract;
}
