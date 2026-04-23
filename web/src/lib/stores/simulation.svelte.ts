/**
 * Simulation state store — Svelte 5 runes.
 * Tracks the full 5-step workflow: seed → graph → agents → simulation → report → chat
 */

export type SimStep = "seed" | "graph" | "agents" | "simulate" | "report" | "chat";

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  color?: string;
  properties?: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  label?: string;
}

export interface AgentProfile {
  agent_id: string;
  name: string;
  budget: number;
  spent: number;
  price_sensitivity: number;
  brand_loyalty: number;
  risk_tolerance: number;
  preferred_categories: string[];
  protocol_preference: string | null;
  state: string;
  city: string;
}

export interface SimEvent {
  type: string;
  [key: string]: unknown;
}

export interface AgentMemoryEvent {
  round_num: number;
  agent_id: string;
  agent_name: string;
  event_type: string;
  protocol: string;
  workload_type: string;
  sentiment_delta: number;
  trust_before: number;
  trust_after: number;
  outcome?: string;
  trust_driver?: string;
  ecosystem_pressure?: number;
  amount_cents: number;
  merchant_id?: string | null;
  merchant_name?: string | null;
  merchant_reputation?: number | null;
  product_name?: string | null;
  route_id?: string | null;
  reason: string;
}

export interface EconomyWorldEvent {
  round_num: number;
  event_type: string;
  summary: string;
  actor_id?: string | null;
  protocol?: string | null;
  data?: Record<string, unknown>;
}

export interface ProtoMetrics {
  protocol: string;
  total_transactions: number;
  successful_transactions: number;
  failed_transactions: number;
  total_volume_cents: number;
  total_fees_cents: number;
  avg_settlement_ms: number;
  avg_authorization_ms: number;
  micropayment_count: number;
}

export interface ProtocolEcosystem {
  merchant_count: number;
  network_effect: number;
  congestion: number;
  operator_margin_cents: number;
  reliability?: number;
  route_mix?: Record<string, number>;
}

export interface BalanceSnapshot {
  owner_kind: string;
  owner_id: string;
  domain: string;
  available_cents: number;
  reserved_cents: number;
  pending_in_cents: number;
  pending_out_cents: number;
}

export interface RoutePressureSummary {
  route_id: string;
  source_domain: string;
  target_domain: string;
  primitive: string;
  protocols: string[];
  total_usage_cents: number;
  max_capacity_ratio: number;
  pressure_rounds: number;
  last_pressure_level: string;
  reason?: string | null;
  merchant_id?: string | null;
  merchant?: string | null;
  failure_count?: number;
}

export interface TreasuryPostureSummary {
  merchant_id: string;
  merchant: string;
  preferred_domain: string;
  max_preferred_shortfall_cents: number;
  min_preferred_ratio: number;
  rebalance_ready_rounds: number;
  last_preferred_ratio: number;
  last_total_treasury_cents: number;
}

export interface EconomyObservabilityStoreFields {
  metrics: ProtoMetrics[];
  ecosystem: Record<string, ProtocolEcosystem>;
  routeUsage: Record<string, number>;
  railPnlHistory: Record<string, number[]>;
  worldEvents: EconomyWorldEvent[];
  events: SimEvent[];
}

export interface SimConfig {
  num_agents: number;
  num_rounds: number;
  protocols: string[];
  seed: number;
  use_llm: boolean;
  llm_model: string;
  merchantsPerCategory: number;
  flowMix: Record<string, number>;
  stableUniverse: string;
  worldSeed: string;
  scenarioPrompt: string;
  marketLearningRate: number;
  socialMemoryStrength: number;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

export const simState = createSimState();

function createSimState() {
  let step = $state<SimStep>("seed");
  let seedText = $state("");
  let graphNodes = $state<GraphNode[]>([]);
  let graphEdges = $state<GraphEdge[]>([]);
  let agents = $state<AgentProfile[]>([]);
  let events = $state<SimEvent[]>([]);
  let logs = $state<{ time: string; message: string; level?: string }[]>([]);
  let running = $state(false);
  let complete = $state(false);
  let metrics = $state<ProtoMetrics[]>([]);
  let config = $state<SimConfig>({
    num_agents: 50,
    num_rounds: 10,
    protocols: [],
    seed: 42,
    use_llm: false,
    llm_model: "minimax-m2.5",
    merchantsPerCategory: 3,
    flowMix: {
      api_micro: 0.55,
      consumer_checkout: 0.3,
      treasury_rebalance: 0.15,
    },
    stableUniverse: "usdc_centric",
    worldSeed: "meridian-protocol-economy",
    scenarioPrompt: "",
    marketLearningRate: 1,
    socialMemoryStrength: 0.35,
  });
  let elapsed = $state("");
  let totalTxns = $state(0);
  let totalVolume = $state(0);
  let reportSections = $state<{ title: string; content: string; status: string }[]>([]);
  let chatMessages = $state<{ role: string; content: string; agent?: string }[]>([]);
  let ecosystem = $state<Record<string, ProtocolEcosystem>>({});
  let balances = $state<BalanceSnapshot[]>([]);
  let routeUsage = $state<Record<string, number>>({});
  let treasuryDistribution = $state<Record<string, Record<string, number>>>({});
  let railPnlHistory = $state<Record<string, number[]>>({});
  let floatSummary = $state<Record<string, number>>({});
  let routePressureSummary = $state<RoutePressureSummary[]>([]);
  let treasuryPostureSummary = $state<TreasuryPostureSummary[]>([]);
  let trustSummary = $state<Record<string, { avg: number; min: number; max: number }>>({});
  let agentMemories = $state<AgentMemoryEvent[]>([]);
  let worldEvents = $state<EconomyWorldEvent[]>([]);

  // Derived
  let purchases = $derived(events.filter((e) => e.type === "purchase"));
  let failures = $derived(events.filter((e) => e.type === "purchase_failed"));
  let rounds = $derived(events.filter((e) => e.type === "round_complete"));
  let canAdvance = $derived({
    seed: seedText.length > 0 || graphNodes.length > 0,
    graph: graphNodes.length > 0,
    agents: agents.length > 0,
    simulate: complete,
    report: reportSections.length > 0,
    chat: true,
  });

  function addLog(message: string, level?: string) {
    const time = new Date().toLocaleTimeString("en-US", { hour12: false });
    logs = [...logs, { time, message, level }];
  }

  function reset() {
    step = "seed";
    seedText = "";
    graphNodes = [];
    graphEdges = [];
    agents = [];
    events = [];
    logs = [];
    running = false;
    complete = false;
    metrics = [];
    elapsed = "";
    totalTxns = 0;
    totalVolume = 0;
    reportSections = [];
    chatMessages = [];
    ecosystem = {};
    balances = [];
    routeUsage = {};
    treasuryDistribution = {};
    railPnlHistory = {};
    floatSummary = {};
    routePressureSummary = [];
    treasuryPostureSummary = [];
    trustSummary = {};
    agentMemories = [];
    worldEvents = [];
  }

  return {
    get step() {
      return step;
    },
    set step(v: SimStep) {
      step = v;
    },
    get seedText() {
      return seedText;
    },
    set seedText(v: string) {
      seedText = v;
    },
    get graphNodes() {
      return graphNodes;
    },
    set graphNodes(v: GraphNode[]) {
      graphNodes = v;
    },
    get graphEdges() {
      return graphEdges;
    },
    set graphEdges(v: GraphEdge[]) {
      graphEdges = v;
    },
    get agents() {
      return agents;
    },
    set agents(v: AgentProfile[]) {
      agents = v;
    },
    get events() {
      return events;
    },
    set events(v: SimEvent[]) {
      events = v;
    },
    get logs() {
      return logs;
    },
    get running() {
      return running;
    },
    set running(v: boolean) {
      running = v;
    },
    get complete() {
      return complete;
    },
    set complete(v: boolean) {
      complete = v;
    },
    get metrics() {
      return metrics;
    },
    set metrics(v: ProtoMetrics[]) {
      metrics = v;
    },
    get config() {
      return config;
    },
    set config(v: SimConfig) {
      config = v;
    },
    get elapsed() {
      return elapsed;
    },
    set elapsed(v: string) {
      elapsed = v;
    },
    get totalTxns() {
      return totalTxns;
    },
    set totalTxns(v: number) {
      totalTxns = v;
    },
    get totalVolume() {
      return totalVolume;
    },
    set totalVolume(v: number) {
      totalVolume = v;
    },
    get purchases() {
      return purchases;
    },
    get failures() {
      return failures;
    },
    get rounds() {
      return rounds;
    },
    get canAdvance() {
      return canAdvance;
    },
    get reportSections() {
      return reportSections;
    },
    set reportSections(v: typeof reportSections) {
      reportSections = v;
    },
    get chatMessages() {
      return chatMessages;
    },
    set chatMessages(v: typeof chatMessages) {
      chatMessages = v;
    },
    get ecosystem() {
      return ecosystem;
    },
    set ecosystem(v: Record<string, ProtocolEcosystem>) {
      ecosystem = v;
    },
    get balances() {
      return balances;
    },
    set balances(v: BalanceSnapshot[]) {
      balances = v;
    },
    get routeUsage() {
      return routeUsage;
    },
    set routeUsage(v: Record<string, number>) {
      routeUsage = v;
    },
    get treasuryDistribution() {
      return treasuryDistribution;
    },
    set treasuryDistribution(v: Record<string, Record<string, number>>) {
      treasuryDistribution = v;
    },
    get railPnlHistory() {
      return railPnlHistory;
    },
    set railPnlHistory(v: Record<string, number[]>) {
      railPnlHistory = v;
    },
    get floatSummary() {
      return floatSummary;
    },
    set floatSummary(v: Record<string, number>) {
      floatSummary = v;
    },
    get routePressureSummary() {
      return routePressureSummary;
    },
    set routePressureSummary(v: RoutePressureSummary[]) {
      routePressureSummary = v;
    },
    get treasuryPostureSummary() {
      return treasuryPostureSummary;
    },
    set treasuryPostureSummary(v: TreasuryPostureSummary[]) {
      treasuryPostureSummary = v;
    },
    get trustSummary() {
      return trustSummary;
    },
    set trustSummary(v: Record<string, { avg: number; min: number; max: number }>) {
      trustSummary = v;
    },
    get agentMemories() {
      return agentMemories;
    },
    set agentMemories(v: AgentMemoryEvent[]) {
      agentMemories = v;
    },
    get worldEvents() {
      return worldEvents;
    },
    set worldEvents(v: EconomyWorldEvent[]) {
      worldEvents = v;
    },
    addLog,
    reset,
  };
}
