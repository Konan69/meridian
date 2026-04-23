<script lang="ts">
	import { onMount } from 'svelte';
	import { simState, type SimStep } from '$lib/stores/simulation.svelte';
	import {
		describeStreamEvent,
		finalNdjsonLine,
		normalizeAgentMemoryEvent,
		normalizeAgentMemoryEvents,
		normalizeBalanceSnapshots,
		normalizeEcosystemSummary,
		normalizeNestedNumberRecord,
		normalizeNumberArrayRecord,
		normalizeNumberRecord,
		normalizeProtocolSummaries,
		normalizeRoutePressureSummaries,
		normalizeTimelineEvent,
		normalizeTreasuryPostureSummaries,
		normalizeTrustSummary,
		normalizeWorldEvent,
		normalizeWorldEvents,
		numberFrom,
		parseSimulationEvent,
		splitNdjsonChunk,
	} from '$lib/simStream';
	import StepIndicator from '$lib/components/StepIndicator.svelte';
	import GraphPanel from '$lib/components/GraphPanel.svelte';
	import Timeline from '$lib/components/Timeline.svelte';
	import AgentCard from '$lib/components/AgentCard.svelte';
	import SystemLogs from '$lib/components/SystemLogs.svelte';
	import ChatPanel from '$lib/components/ChatPanel.svelte';
	import MarketCharts from '$lib/components/MarketCharts.svelte';
	import { generateDemoGraph } from '$lib/components/graphDemo';

	const ENGINE = 'http://localhost:4080';
	type CapabilityStatus = {
		protocol: string;
		runtime_ready: boolean;
		integration: string;
		reason: string;
	};
	type ChatStatus = {
		enabled: boolean;
		provider: string;
		model: string;
		baseURL: string;
		reason?: string;
	};

	let chatLoading = $state(false);
	let supportedProtocols = $state<string[]>([]);
	let capabilityStatuses = $state<CapabilityStatus[]>([]);
	let chatStatus = $state<ChatStatus | null>(null);
	let chatAvailable = $derived(Boolean(chatStatus?.enabled));

	onMount(async () => {
		await Promise.all([loadCapabilities(), loadChatStatus()]);
	});

	async function loadCapabilities() {
		const res = await fetch(`${ENGINE}/capabilities`);
		if (!res.ok) {
			throw new Error(`Capabilities request failed: ${res.status}`);
		}
		const data = await res.json();
		if (!Array.isArray(data.supported_protocols)) {
			throw new Error('Capabilities response missing supported_protocols');
		}
		supportedProtocols = data.supported_protocols;
		capabilityStatuses = Array.isArray(data.protocol_statuses) ? data.protocol_statuses : [];
		simState.config = {
			...simState.config,
			protocols: supportedProtocols,
		};
	}

	async function loadChatStatus() {
		try {
			const res = await fetch('/api/chat');
			if (!res.ok) {
				chatStatus = {
					enabled: false,
					provider: 'opencode-go',
					model: 'unknown',
					baseURL: '',
					reason: `Chat status request failed: ${res.status}`,
				};
				return;
			}
			chatStatus = await res.json() as ChatStatus;
		} catch (error) {
			chatStatus = {
				enabled: false,
				provider: 'opencode-go',
				model: 'unknown',
				baseURL: '',
				reason: `Chat status request failed: ${error}`,
			};
		}
	}

	function buildChatContext(): string {
		const m = simState.metrics;
		const capabilityLines = capabilityStatuses.map((status) =>
			`  ${status.protocol.toUpperCase()}: ${status.runtime_ready ? 'live' : 'not live'} · ${status.integration} · ${status.reason}`
		);
		const ecosystemLines = Object.entries(simState.ecosystem).map(([protocol, state]) =>
			`  ${protocol.toUpperCase()}: merchants ${state.merchant_count}, network effect ${state.network_effect.toFixed(2)}, congestion ${state.congestion.toFixed(2)}, operator margin ${fmt(state.operator_margin_cents)}`
		);
		const floatLines = Object.entries(simState.floatSummary).map(([domain, amount]) =>
			`  ${domain}: ${fmt(amount)}`
		);
		const routeLines = Object.entries(simState.routeUsage)
			.sort(([, a], [, b]) => b - a)
			.map(([route, count]) => `  ${route}: ${count}`);
		const routePressureLines = simState.routePressureSummary.slice(0, 6).map((route) =>
			`  ${route.route_id}: peak ${pct(route.max_capacity_ratio)}, ${route.pressure_rounds} pressure rounds, ${route.source_domain} to ${route.target_domain}`
		);
		const treasuryPostureLines = simState.treasuryPostureSummary.slice(0, 6).map((posture) =>
			`  ${posture.merchant}: ${pct(posture.min_preferred_ratio)} min preferred ${posture.preferred_domain}, max shortfall ${fmt(posture.max_preferred_shortfall_cents)}, rebalance-ready rounds ${posture.rebalance_ready_rounds}`
		);
		const trustLines = Object.entries(simState.trustSummary).map(([protocol, trust]) =>
			`  ${protocol.toUpperCase()}: avg ${trust.avg.toFixed(2)}, min ${trust.min.toFixed(2)}, max ${trust.max.toFixed(2)}`
		);
		const memoryLines = simState.agentMemories.slice(-8).map((memory) =>
			`  R${memory.round_num} ${memory.agent_name}: ${memory.protocol.toUpperCase()} trust ${memory.trust_before.toFixed(2)} -> ${memory.trust_after.toFixed(2)} (${memory.trust_driver ?? memory.reason})`
		);
		const driverLines = trustDriverRows(6).map((driver) =>
			`  ${formatLabel(driver.label)}: ${driver.count} memories, net trust ${signed(driver.delta)}`
		);
		const worldLines = simState.worldEvents.slice(-8).map((event) =>
			`  R${event.round_num}: ${event.summary}`
		);
		const lines = [
			`Simulation: ${simState.totalTxns} transactions, volume ${fmt(simState.totalVolume)}, duration ${simState.elapsed}, ${simState.config.num_agents} agents, ${simState.config.num_rounds} rounds.`,
			`World seed: ${simState.config.worldSeed}.`,
			simState.config.scenarioPrompt ? `Scenario: ${simState.config.scenarioPrompt}` : '',
			`Engine-supported protocols: ${supportedProtocols.map((protocol) => protocol.toUpperCase()).join(', ')}.`,
			'Protocol readiness:',
			...capabilityLines,
			'Protocol metrics:',
			...m.map(p =>
				`  ${p.protocol.toUpperCase()}: ${p.successful_transactions}/${p.total_transactions} txns, volume ${fmt(p.total_volume_cents)}, fees ${fmt(p.total_fees_cents)} (${p.total_volume_cents > 0 ? ((p.total_fees_cents / p.total_volume_cents) * 100).toFixed(2) : 0}%), avg settlement ${ms(p.avg_settlement_ms)}, micropayments ${p.micropayment_count}`
			),
			'Ecosystem state:',
			...ecosystemLines,
			'Stablecoin float:',
			...floatLines,
			'Route usage:',
			...routeLines,
			'Route pressure:',
			...routePressureLines,
			'Treasury posture:',
			...treasuryPostureLines,
			'Agent trust:',
			...trustLines,
			'Contextual trust drivers:',
			...driverLines,
			'Recent agent memories:',
			...memoryLines,
			'Recent world events:',
			...worldLines,
		];
		return lines.filter(Boolean).join('\n');
	}

	async function handleChatSend(message: string) {
		simState.chatMessages = [...simState.chatMessages, { role: 'user', content: message }];
		chatLoading = true;

		try {
			if (!chatStatus) {
				await loadChatStatus();
			}
			if (!chatStatus?.enabled) {
				simState.chatMessages = [
					...simState.chatMessages,
					{ role: 'assistant', content: `Error: ${chatStatus?.reason || 'Chat is unavailable'}` },
				];
				chatLoading = false;
				return;
			}
			if (supportedProtocols.length === 0) {
				await loadCapabilities();
			}
			const apiMessages = simState.chatMessages.map(m => ({ role: m.role, content: m.content }));
			const res = await fetch('/api/chat', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					messages: apiMessages,
					context: buildChatContext(),
					supportedProtocols,
				}),
			});

			const body = await res.json().catch(() => ({}));
			if (!res.ok) {
				simState.chatMessages = [
					...simState.chatMessages,
					{ role: 'assistant', content: `Error: ${body.error || 'Request failed'}` },
				];
				chatLoading = false;
				return;
			}

			simState.chatMessages = [
				...simState.chatMessages,
				{ role: 'assistant', content: typeof body.text === 'string' && body.text.trim() ? body.text : 'No response returned.' },
			];
		} catch (e) {
			simState.chatMessages = [...simState.chatMessages, { role: 'assistant', content: `Connection error: ${e}` }];
		}
		chatLoading = false;
	}

	function fmt(n: number) { return `$${(n / 100).toFixed(2)}`; }
	function ms(n: number) { return n < 1 ? `${(n * 1000).toFixed(0)}μs` : n < 100 ? `${n.toFixed(2)}ms` : `${n.toFixed(0)}ms`; }
	function pct(n: number) { return `${(n * 100).toFixed(0)}%`; }
	function signed(n: number) { return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`; }
	function formatLabel(value: string) { return value.replaceAll('_', ' '); }
	function topEntries<T>(record: Record<string, T>, limit = 6) {
		return Object.entries(record).slice(0, limit);
	}
	function trustDriverRows(limit = 4) {
		const rows = new Map<string, { label: string; count: number; delta: number }>();
		for (const memory of simState.agentMemories) {
			const label = memory.trust_driver ?? memory.reason ?? memory.outcome ?? 'memory_event';
			const row = rows.get(label) ?? { label, count: 0, delta: 0 };
			row.count += 1;
			row.delta += memory.sentiment_delta;
			rows.set(label, row);
		}
		return Array.from(rows.values())
			.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || b.count - a.count)
			.slice(0, limit);
	}
	function marginRows(limit = 4) {
		return Object.entries(simState.ecosystem)
			.map(([protocol, state]) => ({ protocol, margin: state.operator_margin_cents }))
			.sort((a, b) => Math.abs(b.margin) - Math.abs(a.margin))
			.slice(0, limit);
	}

	type PurchaseLike = {
		agent?: unknown;
		merchant?: unknown;
		protocol?: unknown;
		amount_cents?: unknown;
	};
	const timelineTypes = new Set(['purchase', 'purchase_failed', 'agent_memory', 'world_event', 'agent_preference_shift']);

	// View mode for split panel (MiroFish pattern)
	let viewMode = $state<'graph' | 'split' | 'workbench'>('split');
	const viewModes = [
		{ key: 'graph', label: 'Graph' },
		{ key: 'split', label: 'Split' },
		{ key: 'workbench', label: 'Workbench' },
	] as const;

	function goToStep(step: SimStep) {
		simState.step = step;
	}

	// Step 1: Seed data
	async function loadSeedData() {
		const scenario = simState.seedText.trim();
		simState.config = {
			...simState.config,
			scenarioPrompt: scenario,
			worldSeed: scenario
				? `meridian-${scenario.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48)}`
				: 'meridian-protocol-economy',
		};
		simState.addLog(
			scenario
				? 'Captured economy seed and attached it to the simulation world.'
				: 'Loading Meridian demo graph scaffold as the economy seed.',
		);
		const demo = generateDemoGraph();
		const seedNode = scenario
			? [{
				id: 'scenario_seed',
				name: scenario.slice(0, 72),
				type: 'Scenario',
			}]
			: [];
		simState.graphNodes = [...seedNode, ...demo.nodes];
		simState.graphEdges = demo.edges;
		simState.addLog(`Loaded ${demo.nodes.length} demo entities and ${demo.edges.length} demo relationships`);
		simState.step = 'graph';
	}

	// Step 2: Graph built — auto-advance
	function advanceFromGraph() {
		simState.addLog('Knowledge graph ready. Generating agent profiles...');
		generateAgents();
		simState.step = 'agents';
	}

	// Step 3: Generate agents
	async function generateAgents() {
		simState.addLog(`Generating ${simState.config.num_agents} agent profiles...`);
		try {
			if (supportedProtocols.length === 0) {
				await loadCapabilities();
			}
			if (supportedProtocols.length === 0) {
				throw new Error('Engine reported no supported protocols');
			}
			const productsRes = await fetch(`${ENGINE}/products`);
			if (!productsRes.ok) {
				throw new Error(`Products request failed: ${productsRes.status}`);
			}
			await productsRes.json();
			// Create agent profiles locally (mirrors Python sim/sim/agents.py)
			const agents = [];
			const states = [
				{ s: 'CA', c: 'San Francisco' }, { s: 'NY', c: 'New York' },
				{ s: 'TX', c: 'Austin' }, { s: 'WA', c: 'Seattle' },
				{ s: 'IL', c: 'Chicago' }, { s: 'FL', c: 'Miami' },
				{ s: 'CO', c: 'Denver' }, { s: 'MA', c: 'Boston' },
				{ s: 'GA', c: 'Atlanta' }, { s: 'OR', c: 'Portland' },
			];
			const categories = ['footwear', 'electronics', 'food', 'digital', 'hardware'];
			const names = ['Alice', 'Bob', 'Carol', 'Dave', 'Eve', 'Frank', 'Grace', 'Hank', 'Iris', 'Jake', 'Kate', 'Leo', 'Maya', 'Nick', 'Olga'];

			for (let i = 0; i < simState.config.num_agents; i++) {
				const st = states[i % states.length];
				agents.push({
					agent_id: `agent_${String(i).padStart(4, '0')}`,
					name: `${names[i % names.length]}_${i}`,
					budget: 5000 + Math.floor(Math.random() * 45000),
					spent: 0,
					price_sensitivity: 0.2 + Math.random() * 0.7,
					brand_loyalty: 0.1 + Math.random() * 0.7,
					risk_tolerance: 0.2 + Math.random() * 0.6,
					preferred_categories: categories.sort(() => Math.random() - 0.5).slice(0, 1 + Math.floor(Math.random() * 2)),
					protocol_preference: Math.random() < 0.3 ? supportedProtocols[Math.floor(Math.random() * supportedProtocols.length)] : null,
					state: st.s,
					city: st.c,
				});
			}
			simState.agents = agents;
			simState.addLog(`${agents.length} agents ready across ${states.length} states`);

			// Add agents to graph
			const agentNodes = agents.slice(0, 10).map(a => ({
				id: a.agent_id,
				name: a.name,
				type: 'Buyer',
			}));
			simState.graphNodes = [...simState.graphNodes, ...agentNodes];
		} catch (e) {
			simState.addLog(`Error: ${e}`, 'error');
		}
	}

	// Step 4: Run simulation
	async function runSimulation() {
		simState.running = true;
		simState.complete = false;
		simState.events = [];
		simState.agentMemories = [];
		simState.worldEvents = [];
		simState.trustSummary = {};
		simState.routePressureSummary = [];
		simState.treasuryPostureSummary = [];
		simState.addLog('Starting simulation...');

		try {
			if (supportedProtocols.length === 0) {
				await loadCapabilities();
			}
			if (simState.config.protocols.length === 0) {
				throw new Error('No engine-supported protocols available for simulation');
			}
			const res = await fetch('/api/simulate', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					agents: simState.config.num_agents,
					rounds: simState.config.num_rounds,
					protocols: simState.config.protocols,
					merchantsPerCategory: simState.config.merchantsPerCategory,
					flowMix: simState.config.flowMix,
					stableUniverse: simState.config.stableUniverse,
					worldSeed: simState.config.worldSeed,
					scenarioPrompt: simState.config.scenarioPrompt,
					marketLearningRate: simState.config.marketLearningRate,
					socialMemoryStrength: simState.config.socialMemoryStrength,
				}),
			});

			const reader = res.body?.getReader();
			if (!res.ok || !reader) {
				throw new Error(`Simulation stream failed: ${res.status}`);
			}
			const dec = new TextDecoder();
			let buf = '';
			let skippedStreamLines = 0;

			const processStreamLine = (line: string) => {
				const parsed = parseSimulationEvent(line);
				if (!parsed.ok) {
					skippedStreamLines += 1;
					return;
				}

				const ev = normalizeTimelineEvent(parsed.event);
				simState.events = [...simState.events.slice(-499), ev];
				const description = describeStreamEvent(ev);
				simState.addLog(description ? `[${ev.type}] ${description}` : `[${ev.type}]`);

				const memory = normalizeAgentMemoryEvent(ev);
				if (memory) {
					simState.agentMemories = [
						...simState.agentMemories.slice(-199),
						memory,
					];
				}

				const worldEvent = normalizeWorldEvent(ev);
				if (worldEvent) {
					simState.worldEvents = [
						...simState.worldEvents.slice(-199),
						worldEvent,
					];
				}

				if (ev.type === 'trust_snapshot') {
					simState.trustSummary = normalizeTrustSummary(ev.trust_summary);
				}

				if (ev.type === 'simulation_complete') {
					const completeMemories = normalizeAgentMemoryEvents(ev.agent_memory_log);
					const completeWorldEvents = normalizeWorldEvents(ev.world_events);

					simState.complete = true;
					simState.elapsed = `${numberFrom(ev.duration_seconds) ?? 0}s`;
					simState.totalTxns = numberFrom(ev.total_transactions) ?? 0;
					simState.totalVolume = numberFrom(ev.total_volume_cents) ?? 0;
					simState.metrics = normalizeProtocolSummaries(ev.protocol_summaries);
					simState.ecosystem = normalizeEcosystemSummary(ev.ecosystem_summary);
					simState.balances = normalizeBalanceSnapshots(ev.balances);
					simState.routeUsage = normalizeNumberRecord(ev.route_usage_summary);
					simState.routePressureSummary = normalizeRoutePressureSummaries(ev.route_pressure_summary);
					simState.floatSummary = normalizeNumberRecord(ev.float_summary);
					simState.treasuryDistribution = normalizeNestedNumberRecord(ev.treasury_distribution);
					simState.treasuryPostureSummary = normalizeTreasuryPostureSummaries(ev.treasury_posture_summary);
					simState.railPnlHistory = normalizeNumberArrayRecord(ev.rail_pnl_history);
					simState.trustSummary = normalizeTrustSummary(ev.trust_summary);
					simState.agentMemories = completeMemories ?? simState.agentMemories;
					simState.worldEvents = completeWorldEvents ?? simState.worldEvents;

					// Add transaction edges to graph
					const txEdges = simState.purchases
						.slice(0, 20)
						.flatMap((purchase) => {
							const p = purchase as PurchaseLike;
							if (
								typeof p.agent !== 'string' ||
								typeof p.protocol !== 'string' ||
								typeof p.amount_cents !== 'number'
							) {
								return [];
							}
							const target =
								typeof p.merchant === 'string'
									? p.merchant
									: `merchant_${p.protocol}`;
							return [{
								source: p.agent,
								target,
								label: `${p.protocol} ${fmt(p.amount_cents)}`,
							}];
						});
					const merchantNodes = Array.from(
						new Set(
							simState.purchases
								.map((p) => p.merchant)
								.filter((merchant): merchant is string => Boolean(merchant))
						)
					).map((merchant) => ({
						id: merchant,
						name: merchant,
						type: 'Merchant',
					}));
					simState.graphNodes = [...simState.graphNodes, ...merchantNodes];
					simState.graphEdges = [...simState.graphEdges, ...txEdges];
				}
			};

			while (reader) {
				const { done, value } = await reader.read();
				if (done) break;
				const chunk = splitNdjsonChunk(buf, dec.decode(value, { stream: true }));
				buf = chunk.buffer;
				chunk.lines.forEach(processStreamLine);
			}

			const trailing = splitNdjsonChunk(buf, dec.decode());
			buf = trailing.buffer;
			trailing.lines.forEach(processStreamLine);
			const finalLine = finalNdjsonLine(buf);
			if (finalLine) {
				processStreamLine(finalLine);
			}
			if (skippedStreamLines > 0) {
				simState.addLog(`Skipped ${skippedStreamLines} malformed stream event${skippedStreamLines === 1 ? '' : 's'}.`, 'warn');
			}
		} catch (e) {
			simState.addLog(`Error: ${e}`, 'error');
		}
		simState.running = false;
	}

	// Step 5: Generate report
	function generateReport() {
		simState.addLog('Generating protocol comparison report...');
		const m = simState.metrics;
		simState.reportSections = [
			{
				title: 'Executive Summary',
				content: `Simulation completed with ${simState.totalTxns} transactions across ${simState.metrics.length} live protocols. Total volume: ${fmt(simState.totalVolume)}. Duration: ${simState.elapsed}.`,
				status: 'complete',
			},
			{
				title: 'Ecosystem Dynamics',
				content: Object.entries(simState.ecosystem).map(([protocol, state]) =>
					`${protocol.toUpperCase()}: ${state.merchant_count} merchants, network effect ${state.network_effect.toFixed(2)}, congestion ${state.congestion.toFixed(2)}, operator margin ${fmt(state.operator_margin_cents)}`
				).join('\n'),
				status: 'complete',
			},
			{
				title: 'Emergent Agent Economy',
				content: [
					`World seed: ${simState.config.worldSeed}`,
					simState.config.scenarioPrompt ? `Scenario: ${simState.config.scenarioPrompt}` : '',
					`Agent memories: ${simState.agentMemories.length}`,
					`World events: ${simState.worldEvents.length}`,
					...Object.entries(simState.trustSummary).map(([protocol, trust]) =>
						`${protocol.toUpperCase()}: trust avg ${trust.avg.toFixed(2)}, min ${trust.min.toFixed(2)}, max ${trust.max.toFixed(2)}`
					),
					...simState.worldEvents.slice(-4).map((event) => `R${event.round_num}: ${event.summary}`),
				].filter(Boolean).join('\n'),
				status: 'complete',
			},
			{
				title: 'Self-Sustainability Signals',
				content: [
					...simState.treasuryPostureSummary.slice(0, 4).map((posture) =>
						`${posture.merchant}: ${pct(posture.min_preferred_ratio)} min preferred ${posture.preferred_domain}, max shortfall ${fmt(posture.max_preferred_shortfall_cents)}, rebalance-ready rounds ${posture.rebalance_ready_rounds}`
					),
					...simState.routePressureSummary.slice(0, 4).map((route) =>
						`${route.route_id}: peak ${pct(route.max_capacity_ratio)}, pressure rounds ${route.pressure_rounds}, ${route.source_domain} to ${route.target_domain}`
					),
					...trustDriverRows(4).map((driver) =>
						`${formatLabel(driver.label)}: ${driver.count} memories, net trust ${signed(driver.delta)}`
					),
				].join('\n') || 'No rebalance, route pressure, or contextual memory signal recorded.',
				status: 'complete',
			},
			{
				title: 'Stablecoin Float',
				content: Object.entries(simState.floatSummary)
					.sort(([, a], [, b]) => b - a)
					.map(([domain, amount]) => `${domain}: ${fmt(amount)}`)
					.join('\n'),
				status: 'complete',
			},
			...m.map(p => ({
				title: `${p.protocol.toUpperCase()} Protocol Analysis`,
				content: `${p.successful_transactions}/${p.total_transactions} transactions successful. Volume: ${fmt(p.total_volume_cents)}. Fees: ${fmt(p.total_fees_cents)} (${p.total_volume_cents > 0 ? ((p.total_fees_cents / p.total_volume_cents) * 100).toFixed(2) : 0}%). Average execution: ${ms(p.avg_settlement_ms)}. Micropayments: ${p.micropayment_count}.`,
				status: 'complete',
			})),
			{
				title: 'Comparative Analysis',
				content: `Fastest protocol: ${m[0]?.protocol.toUpperCase()} at ${ms(m[0]?.avg_settlement_ms || 0)}. Cheapest: ${m.sort((a, b) => (a.total_volume_cents > 0 ? a.total_fees_cents / a.total_volume_cents : 99) - (b.total_volume_cents > 0 ? b.total_fees_cents / b.total_volume_cents : 99))[0]?.protocol.toUpperCase()}.`,
				status: 'complete',
			},
			{
				title: 'Rail P&L',
				content: Object.entries(simState.ecosystem)
					.sort(([, a], [, b]) => b.operator_margin_cents - a.operator_margin_cents)
					.map(([protocol, state]) => `${protocol.toUpperCase()}: margin ${fmt(state.operator_margin_cents)}`)
					.join('\n'),
				status: 'complete',
			},
			{
				title: 'Route Usage',
				content: Object.entries(simState.routeUsage)
					.sort(([, a], [, b]) => b - a)
					.map(([route, count]) => `${route}: ${count}`)
					.join('\n'),
				status: 'complete',
			},
		];
		simState.step = 'report';
	}
</script>

<div class="sim-shell" style="display:flex; flex-direction:column; height:calc(100vh - 56px - 56px);">
	<!-- Step bar (MiroFish header pattern) -->
	<div class="step-bar" style="
		padding:8px 24px;
		border-bottom:1px solid var(--bd);
		background:var(--bg-1);
		display:flex;
		align-items:center;
		justify-content:space-between;
	">
		<StepIndicator currentStep={simState.step} onStepClick={goToStep} />

		<!-- View mode switcher (MiroFish pattern) -->
		<div role="group" aria-label="View mode selector" style="display:flex; gap:2px; background:var(--bg-2); padding:3px; border-radius:6px;">
			{#each viewModes as mode}
				<button
					onclick={() => viewMode = mode.key}
					aria-pressed={viewMode === mode.key}
					style="
						font-size:11px; font-weight:600; padding:8px 16px; border:none;
						border-radius:4px; cursor:pointer;
						background:{viewMode === mode.key ? 'var(--bg-4)' : 'transparent'};
						color:{viewMode === mode.key ? 'var(--tx-1)' : 'var(--tx-3)'};
					"
				>{mode.label}</button>
			{/each}
		</div>
	</div>

	<!-- Main content: split view -->
	<div class="sim-panels" style="flex:1; display:flex; overflow:hidden;">
		<!-- Left: Graph panel -->
		{#if viewMode !== 'workbench'}
			<div class="graph-pane" style="
				width:{viewMode === 'graph' ? '100%' : '50%'};
				border-right:{viewMode === 'split' ? '1px solid var(--bd)' : 'none'};
				transition:width 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
				overflow:hidden;
			">
				<GraphPanel nodes={simState.graphNodes} edges={simState.graphEdges} />
			</div>
		{/if}

		<!-- Right: Workbench -->
		{#if viewMode !== 'graph'}
			<div class="workbench-pane" style="
				width:{viewMode === 'workbench' ? '100%' : '50%'};
				display:flex; flex-direction:column;
				transition:width 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
				overflow:hidden;
			">
				<!-- Step content -->
				<div style="flex:1; overflow-y:auto; padding:20px;">
					{#if simState.step === 'seed'}
						<!-- Step 1: Seed Data -->
						<div>
							<h2 style="font-size:16px; font-weight:600; margin-bottom:4px;">
								<span style="font-family:var(--mono); color:var(--acp); margin-right:8px;">01</span>
								Scenario Seed
							</h2>
							<p style="font-size:12px; color:var(--tx-3); margin-bottom:20px;">Describe a market scenario. Meridian currently visualizes it with a demo graph scaffold while live ingestion is offline.</p>

							<textarea
								bind:value={simState.seedText}
								placeholder="Describe the market scenario...&#10;&#10;Example: Base-native API buyers, treasury-heavy merchants, and cheap machine-payment routes competing for flow."
								style="
									width:100%; min-height:180px; padding:16px;
									background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
									color:var(--tx-1); font-family:var(--sans); font-size:13px;
									line-height:1.6; resize:vertical;
								"
							></textarea>

							<div class="seed-actions" style="display:flex; gap:10px; margin-top:16px;">
								<button onclick={loadSeedData} style="
									padding:10px 24px; border:none; border-radius:4px;
									background:var(--acp); color:#fff; font-weight:600; font-size:13px;
								">{simState.seedText.trim() ? 'Use Seed + Demo Graph' : 'Use Demo Graph Scaffold'}</button>
								<button onclick={() => { const d = generateDemoGraph(); simState.graphNodes = d.nodes; simState.graphEdges = d.edges; simState.step = 'graph'; }} style="
									padding:10px 24px; border:1px solid var(--bd); border-radius:4px;
									background:transparent; color:var(--tx-2); font-weight:600; font-size:13px;
								">Load Pure Demo Graph</button>
							</div>
						</div>

					{:else if simState.step === 'graph'}
						<!-- Step 2: Knowledge Graph -->
						<div>
							<h2 style="font-size:16px; font-weight:600; margin-bottom:4px;">
								<span style="font-family:var(--mono); color:var(--acp); margin-right:8px;">02</span>
								Knowledge Graph
							</h2>
							<p style="font-size:12px; color:var(--tx-3); margin-bottom:16px;">
								{simState.graphNodes.length} entities · {simState.graphEdges.length} relationships
							</p>

							<div class="entity-grid" style="gap:8px; margin-bottom:20px;">
								{#each [...new Set(simState.graphNodes.map(n => n.type))] as type}
									<div style="background:var(--bg-2); border-radius:4px; padding:12px; text-align:center;">
										<div style="font-family:var(--mono); font-size:20px; font-weight:700;">
											{simState.graphNodes.filter(n => n.type === type).length}
										</div>
										<div style="font-size:10px; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em; margin-top:2px;">{type}</div>
									</div>
								{/each}
							</div>

							<button onclick={advanceFromGraph} style="
								padding:10px 24px; border:none; border-radius:4px;
								background:var(--acp); color:#fff; font-weight:600; font-size:13px;
							">Generate Agent Profiles →</button>
						</div>

					{:else if simState.step === 'agents'}
						<!-- Step 3: Agent Setup -->
						<div>
							<h2 style="font-size:16px; font-weight:600; margin-bottom:4px;">
								<span style="font-family:var(--mono); color:var(--acp); margin-right:8px;">03</span>
								Agent Profiles
							</h2>
							<p style="font-size:12px; color:var(--tx-3); margin-bottom:16px;">
								{simState.agents.length} agents · Total budget: {fmt(simState.agents.reduce((s, a) => s + a.budget, 0))}
							</p>

							<!-- Config editor -->
							<div style="display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap;">
								<label for="cfg-agents" style="display:flex; flex-direction:column; gap:2px;">
									<span style="font-size:8px; font-weight:600; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em;">Agents</span>
									<input id="cfg-agents" type="number" bind:value={simState.config.num_agents} min="10" max="1000" style="
										width:60px; background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
										padding:5px 8px; color:var(--tx-1); font-family:var(--mono); font-size:12px;
									" />
								</label>
								<label for="cfg-rounds" style="display:flex; flex-direction:column; gap:2px;">
									<span style="font-size:8px; font-weight:600; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em;">Rounds</span>
									<input id="cfg-rounds" type="number" bind:value={simState.config.num_rounds} min="1" max="100" style="
										width:60px; background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
										padding:5px 8px; color:var(--tx-1); font-family:var(--mono); font-size:12px;
									" />
								</label>
								<label for="cfg-seed" style="display:flex; flex-direction:column; gap:2px;">
									<span style="font-size:8px; font-weight:600; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em;">Seed</span>
									<input id="cfg-seed" type="number" bind:value={simState.config.seed} style="
										width:60px; background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
										padding:5px 8px; color:var(--tx-1); font-family:var(--mono); font-size:12px;
									" />
								</label>
							</div>

							<!-- Agent cards grid -->
							<div class="agent-grid" style="gap:8px; max-height:400px; overflow-y:auto;">
								{#each simState.agents.slice(0, 20) as agent}
									<AgentCard {agent} />
								{/each}
							</div>
							{#if simState.agents.length > 20}
								<p style="font-size:11px; color:var(--tx-3); margin-top:8px; text-align:center;">
									Showing 20 of {simState.agents.length} agents
								</p>
							{/if}

							<button onclick={() => { simState.step = 'simulate'; runSimulation(); }} style="
								padding:10px 24px; border:none; border-radius:4px; margin-top:16px;
								background:var(--acp); color:#fff; font-weight:600; font-size:13px;
								display:flex; align-items:center; gap:8px;
							">
								▶ Start Simulation
							</button>
						</div>

					{:else if simState.step === 'simulate'}
						<!-- Step 4: Simulation -->
						<div>
							<h2 style="font-size:16px; font-weight:600; margin-bottom:4px;">
								<span style="font-family:var(--mono); color:var(--acp); margin-right:8px;">04</span>
								{simState.running ? 'Simulation Running...' : simState.complete ? 'Simulation Complete' : 'Simulation'}
							</h2>

							{#if simState.complete}
								<!-- Summary -->
								<div class="summary-grid" style="gap:1px; background:var(--bd); border-radius:6px; overflow:hidden; margin:16px 0;">
									{#each [
										{ v: simState.totalTxns, l: 'TRANSACTIONS' },
										{ v: fmt(simState.totalVolume), l: 'VOLUME' },
										{ v: simState.elapsed, l: 'DURATION' },
										{ v: simState.config.num_agents, l: 'AGENTS' },
									] as s}
										<div style="background:var(--bg-2); padding:14px; text-align:center;">
											<div style="font-family:var(--mono); font-size:18px; font-weight:700;">{s.v}</div>
											<div style="font-size:8px; font-weight:600; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.1em; margin-top:3px;">{s.l}</div>
										</div>
									{/each}
								</div>

								<div class="context-grid" style="gap:12px; margin-bottom:16px;">
									<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:14px; min-width:0;">
										<div style="font-size:10px; font-weight:700; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:10px;">Treasury Posture</div>
										{#each simState.treasuryPostureSummary.slice(0, 3) as posture}
											<div style="font-family:var(--mono); font-size:11px; padding:5px 0; border-bottom:1px solid var(--bg-3);">
												<div style="display:flex; justify-content:space-between; gap:10px;">
													<span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{posture.merchant}</span>
													<span>{fmt(posture.max_preferred_shortfall_cents)}</span>
												</div>
												<div style="color:var(--tx-3); margin-top:3px;">{posture.preferred_domain} min {pct(posture.min_preferred_ratio)} · ready {posture.rebalance_ready_rounds}r</div>
											</div>
										{:else}
											<div style="font-family:var(--mono); font-size:11px; color:var(--tx-3);">No posture gaps</div>
										{/each}
									</div>
									<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:14px; min-width:0;">
										<div style="font-size:10px; font-weight:700; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:10px;">Route Pressure</div>
										{#each simState.routePressureSummary.slice(0, 3) as route}
											<div style="font-family:var(--mono); font-size:11px; padding:5px 0; border-bottom:1px solid var(--bg-3);">
												<div style="display:flex; justify-content:space-between; gap:10px;">
													<span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{route.route_id}</span>
													<span>{pct(route.max_capacity_ratio)}</span>
												</div>
												<div style="color:var(--tx-3); margin-top:3px;">{route.source_domain} to {route.target_domain} · {route.pressure_rounds}r</div>
											</div>
										{:else}
											<div style="font-family:var(--mono); font-size:11px; color:var(--tx-3);">No route pressure</div>
										{/each}
									</div>
									<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:14px; min-width:0;">
										<div style="font-size:10px; font-weight:700; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:10px;">Trust Drivers</div>
										{#each trustDriverRows(3) as driver}
											<div style="font-family:var(--mono); font-size:11px; padding:5px 0; border-bottom:1px solid var(--bg-3);">
												<div style="display:flex; justify-content:space-between; gap:10px;">
													<span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{formatLabel(driver.label)}</span>
													<span>{signed(driver.delta)}</span>
												</div>
												<div style="color:var(--tx-3); margin-top:3px;">{driver.count} memories</div>
											</div>
										{:else}
											<div style="font-family:var(--mono); font-size:11px; color:var(--tx-3);">No memory drivers</div>
										{/each}
									</div>
									<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:14px; min-width:0;">
										<div style="font-size:10px; font-weight:700; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:10px;">Rail Margin</div>
										{#each marginRows(3) as row}
											<div style="display:flex; justify-content:space-between; gap:10px; font-family:var(--mono); font-size:11px; padding:5px 0; border-bottom:1px solid var(--bg-3);">
												<span>{row.protocol.toUpperCase()}</span>
												<span>{fmt(row.margin)}</span>
											</div>
										{:else}
											<div style="font-family:var(--mono); font-size:11px; color:var(--tx-3);">No margin signal</div>
										{/each}
									</div>
								</div>

								<button onclick={generateReport} style="
									padding:10px 24px; border:none; border-radius:4px;
									background:var(--acp); color:#fff; font-weight:600; font-size:13px;
								">Generate Report →</button>
							{/if}

							<!-- Timeline -->
							<div style="margin-top:16px;">
								<Timeline events={simState.events.filter((event) => timelineTypes.has(event.type)).slice(-60)} />
							</div>
						</div>

					{:else if simState.step === 'report'}
						<!-- Step 5: Report -->
						<div>
							<h2 style="font-size:16px; font-weight:600; margin-bottom:16px;">
								<span style="font-family:var(--mono); color:var(--acp); margin-right:8px;">05</span>
								Protocol Comparison Report
							</h2>

							{#each simState.reportSections as section, i}
								<div style="
									background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
									padding:16px; margin-bottom:10px;
								">
									<div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
										<span style="font-family:var(--mono); font-size:10px; color:var(--tx-3);">{String(i + 1).padStart(2, '0')}</span>
										<span style="font-weight:600; font-size:14px;">{section.title}</span>
										<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="var(--x402)" stroke-width="3" style="margin-left:auto;">
											<polyline points="20 6 9 17 4 12"></polyline>
										</svg>
									</div>
									<p style="font-size:13px; color:var(--tx-2); line-height:1.6; white-space:pre-wrap;">{section.content}</p>
								</div>
							{/each}

							<button onclick={() => simState.step = 'chat'} disabled={!chatAvailable} style="
								padding:10px 24px; border:none; border-radius:4px; margin-top:8px;
								background:{chatAvailable ? 'var(--acp)' : 'var(--bg-3)'};
								color:{chatAvailable ? '#fff' : 'var(--tx-3)'};
								font-weight:600; font-size:13px;
								cursor:{chatAvailable ? 'pointer' : 'not-allowed'};
							">{chatAvailable ? 'Deep Interaction →' : 'Chat Unavailable'}</button>
							{#if !chatAvailable}
								<p style="font-size:11px; color:var(--tx-3); margin-top:8px;">
									{chatStatus?.reason || 'Chat provider is unavailable for this workspace.'}
								</p>
							{/if}
						</div>

					{:else if simState.step === 'chat'}
						<!-- Step 6: Chat -->
						<div style="display:flex; flex-direction:column; height:100%;">
							<h2 style="font-size:16px; font-weight:600; margin-bottom:12px;">
								<span style="font-family:var(--mono); color:var(--acp); margin-right:8px;">06</span>
								Deep Interaction
							</h2>

							{#if !chatAvailable}
								<div style="
									background:var(--bg-2); border:1px solid var(--bd); border-radius:6px;
									padding:14px; margin-bottom:12px; font-size:12px; color:var(--tx-2);
								">
									<div style="font-weight:600; color:var(--tx-1); margin-bottom:6px;">Chat unavailable</div>
									<div>{chatStatus?.reason || 'The configured provider is unavailable.'}</div>
								</div>
							{/if}

							{#if simState.metrics.length > 0}
								<div style="margin-bottom:12px;">
									<MarketCharts
										metrics={simState.metrics}
										ecosystem={simState.ecosystem}
										routeUsage={simState.routeUsage}
										floatSummary={simState.floatSummary}
										railPnlHistory={simState.railPnlHistory}
									/>
								</div>
							{/if}

							<div style="display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:12px;">
								<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:12px; max-height:220px; overflow:auto;">
									<div style="font-size:10px; font-weight:700; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:8px;">Treasury Distribution</div>
									{#each topEntries(simState.treasuryDistribution, 6) as [merchantId, dist]}
										<div style="padding:6px 0; border-bottom:1px solid var(--bg-3);">
											<div style="font-family:var(--mono); font-size:11px; margin-bottom:4px;">{merchantId}</div>
											{#each Object.entries(dist) as [domain, amount]}
												<div style="display:flex; justify-content:space-between; font-family:var(--mono); font-size:10px; color:var(--tx-2);">
													<span>{domain}</span>
													<span>{fmt(amount)}</span>
												</div>
											{/each}
										</div>
									{/each}
								</div>
								<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:12px; max-height:220px; overflow:auto;">
									<div style="font-size:10px; font-weight:700; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.1em; margin-bottom:8px;">Balance Snapshots</div>
									{#each simState.balances.slice(0, 10) as bucket}
										<div style="padding:6px 0; border-bottom:1px solid var(--bg-3); font-family:var(--mono); font-size:10px;">
											<div>{bucket.owner_kind}:{bucket.owner_id}</div>
											<div style="color:var(--tx-2);">{bucket.domain}</div>
											<div style="display:flex; justify-content:space-between;">
												<span>avail</span>
												<span>{fmt(bucket.available_cents)}</span>
											</div>
											<div style="display:flex; justify-content:space-between; color:var(--tx-3);">
												<span>reserved/pending</span>
												<span>{fmt(bucket.reserved_cents + bucket.pending_in_cents + bucket.pending_out_cents)}</span>
											</div>
										</div>
									{/each}
								</div>
							</div>

							<div style="flex:1; min-height:0;">
								<ChatPanel
									messages={simState.chatMessages.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }))}
									onSend={handleChatSend}
									disabled={chatLoading || !chatAvailable}
								/>
							</div>
						</div>
					{/if}
				</div>

				<!-- System logs (MiroFish terminal panel) -->
				<div style="flex-shrink:0; height:120px; border-top:1px solid var(--bd);">
					<SystemLogs logs={simState.logs} />
				</div>
			</div>
		{/if}
	</div>
</div>

<style>
	.entity-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
	}
	.agent-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
	}
	.summary-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
	}
	.context-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
	}
	.seed-actions {
		flex-wrap: wrap;
	}
	@media (max-width: 1100px) {
		.entity-grid { grid-template-columns: repeat(2, 1fr); }
		.summary-grid { grid-template-columns: repeat(2, 1fr); }
		.context-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
	}
	@media (max-width: 900px) {
		.sim-shell {
			height: auto !important;
			min-height: calc(100vh - 56px - 56px);
		}
		.step-bar {
			flex-wrap: wrap;
			gap: 12px;
			padding: 12px 16px !important;
		}
		.sim-panels {
			flex-direction: column;
			overflow: visible !important;
		}
		.graph-pane {
			width: 100% !important;
			height: min(40vh, 320px);
			border-right: none !important;
			border-bottom: 1px solid var(--bd);
		}
		.workbench-pane {
			width: 100% !important;
			min-height: 0;
		}
	}
	@media (max-width: 768px) {
		.agent-grid { grid-template-columns: 1fr; }
	}
	@media (max-width: 480px) {
		.entity-grid { grid-template-columns: 1fr; }
		.summary-grid { grid-template-columns: 1fr; }
		.context-grid { grid-template-columns: 1fr; }
		.seed-actions button {
			width: 100%;
		}
	}
</style>
