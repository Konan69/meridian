/**
 * Simulation state store — Svelte 5 runes.
 * Tracks the full 5-step workflow: seed → graph → agents → simulation → report → chat
 */

export type SimStep = 'seed' | 'graph' | 'agents' | 'simulate' | 'report' | 'chat';

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
	label: string;
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

export interface SimConfig {
	num_agents: number;
	num_rounds: number;
	protocols: string[];
	seed: number;
	use_llm: boolean;
	llm_model: string;
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

export const simState = createSimState();

function createSimState() {
	let step = $state<SimStep>('seed');
	let seedText = $state('');
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
		protocols: ['acp', 'x402', 'ap2', 'mpp', 'atxp'],
		seed: 42,
		use_llm: false,
		llm_model: 'minimax-m2.5-free',
	});
	let elapsed = $state('');
	let totalTxns = $state(0);
	let totalVolume = $state(0);
	let reportSections = $state<{ title: string; content: string; status: string }[]>([]);
	let chatMessages = $state<{ role: string; content: string; agent?: string }[]>([]);

	// Derived
	let purchases = $derived(events.filter(e => e.type === 'purchase'));
	let failures = $derived(events.filter(e => e.type === 'purchase_failed'));
	let rounds = $derived(events.filter(e => e.type === 'round_complete'));
	let canAdvance = $derived({
		seed: seedText.length > 0 || graphNodes.length > 0,
		graph: graphNodes.length > 0,
		agents: agents.length > 0,
		simulate: complete,
		report: reportSections.length > 0,
		chat: true,
	});

	function addLog(message: string, level?: string) {
		const time = new Date().toLocaleTimeString('en-US', { hour12: false });
		logs = [...logs, { time, message, level }];
	}

	function reset() {
		step = 'seed';
		seedText = '';
		graphNodes = [];
		graphEdges = [];
		agents = [];
		events = [];
		logs = [];
		running = false;
		complete = false;
		metrics = [];
		elapsed = '';
		totalTxns = 0;
		totalVolume = 0;
		reportSections = [];
		chatMessages = [];
	}

	return {
		get step() { return step; },
		set step(v: SimStep) { step = v; },
		get seedText() { return seedText; },
		set seedText(v: string) { seedText = v; },
		get graphNodes() { return graphNodes; },
		set graphNodes(v: GraphNode[]) { graphNodes = v; },
		get graphEdges() { return graphEdges; },
		set graphEdges(v: GraphEdge[]) { graphEdges = v; },
		get agents() { return agents; },
		set agents(v: AgentProfile[]) { agents = v; },
		get events() { return events; },
		set events(v: SimEvent[]) { events = v; },
		get logs() { return logs; },
		get running() { return running; },
		set running(v: boolean) { running = v; },
		get complete() { return complete; },
		set complete(v: boolean) { complete = v; },
		get metrics() { return metrics; },
		set metrics(v: ProtoMetrics[]) { metrics = v; },
		get config() { return config; },
		set config(v: SimConfig) { config = v; },
		get elapsed() { return elapsed; },
		set elapsed(v: string) { elapsed = v; },
		get totalTxns() { return totalTxns; },
		set totalTxns(v: number) { totalTxns = v; },
		get totalVolume() { return totalVolume; },
		set totalVolume(v: number) { totalVolume = v; },
		get purchases() { return purchases; },
		get failures() { return failures; },
		get rounds() { return rounds; },
		get canAdvance() { return canAdvance; },
		get reportSections() { return reportSections; },
		set reportSections(v: typeof reportSections) { reportSections = v; },
		get chatMessages() { return chatMessages; },
		set chatMessages(v: typeof chatMessages) { chatMessages = v; },
		addLog,
		reset,
	};
}
