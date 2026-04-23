import {
  normalizeAgentMemoryEvent,
  normalizeAgentMemoryEvents,
  normalizeRoutePressureSummaries,
  normalizeTreasuryPostureSummaries,
} from './simStream';
import { simState, type AgentMemoryEvent, type RoutePressureSummary, type SimEvent, type TreasuryPostureSummary } from './stores/simulation.svelte';

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

const routePressure: RoutePressureSummary[] = normalizeRoutePressureSummaries(completeEvent.route_pressure_summary);
const treasuryPosture: TreasuryPostureSummary[] = normalizeTreasuryPostureSummaries(completeEvent.treasury_posture_summary);
const batchMemories: AgentMemoryEvent[] = normalizeAgentMemoryEvents(completeEvent.agent_memory_log) ?? [];
const singleMemory = requireMemory(normalizeAgentMemoryEvent(completeEvent.agent_memory_log[0] as SimEvent));

simState.routePressureSummary = routePressure;
simState.treasuryPostureSummary = treasuryPosture;
simState.agentMemories = [...batchMemories, singleMemory];

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
};

function requireMemory(memory: AgentMemoryEvent | null): AgentMemoryEvent {
  if (!memory) throw new Error('agent memory stream contract did not normalize');
  return memory;
}
