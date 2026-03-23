<script lang="ts">
	import { simState, type SimStep } from '$lib/stores/simulation.svelte';
	import StepIndicator from '$lib/components/StepIndicator.svelte';
	import GraphPanel from '$lib/components/GraphPanel.svelte';
	import Timeline from '$lib/components/Timeline.svelte';
	import AgentCard from '$lib/components/AgentCard.svelte';
	import SystemLogs from '$lib/components/SystemLogs.svelte';
	import ChatPanel from '$lib/components/ChatPanel.svelte';
	import MarketCharts from '$lib/components/MarketCharts.svelte';
	import { generateDemoGraph } from '$lib/components/graphDemo';

	const ENGINE = 'http://localhost:4080';

	let chatLoading = $state(false);

	function buildChatContext(): string {
		const m = simState.metrics;
		const lines = [
			`Simulation: ${simState.totalTxns} transactions, volume ${fmt(simState.totalVolume)}, duration ${simState.elapsed}, ${simState.config.num_agents} agents, ${simState.config.num_rounds} rounds.`,
			'Protocol metrics:',
			...m.map(p =>
				`  ${p.protocol.toUpperCase()}: ${p.successful_transactions}/${p.total_transactions} txns, volume ${fmt(p.total_volume_cents)}, fees ${fmt(p.total_fees_cents)} (${p.total_volume_cents > 0 ? ((p.total_fees_cents / p.total_volume_cents) * 100).toFixed(2) : 0}%), avg settlement ${ms(p.avg_settlement_ms)}, micropayments ${p.micropayment_count}`
			),
		];
		return lines.join('\n');
	}

	async function handleChatSend(message: string) {
		simState.chatMessages = [...simState.chatMessages, { role: 'user', content: message }];
		chatLoading = true;

		try {
			const apiMessages = simState.chatMessages.map(m => ({ role: m.role, content: m.content }));
			const res = await fetch('/api/chat', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ messages: apiMessages, context: buildChatContext() }),
			});

			if (!res.ok) {
				const err = await res.json();
				simState.chatMessages = [...simState.chatMessages, { role: 'assistant', content: `Error: ${err.error || 'Request failed'}` }];
				chatLoading = false;
				return;
			}

			// Parse SSE stream
			const reader = res.body?.getReader();
			const dec = new TextDecoder();
			let buf = '';
			let assistantContent = '';
			simState.chatMessages = [...simState.chatMessages, { role: 'assistant', content: '' }];

			while (reader) {
				const { done, value } = await reader.read();
				if (done) break;
				buf += dec.decode(value, { stream: true });
				const lines = buf.split('\n');
				buf = lines.pop() || '';

				for (const line of lines) {
					if (!line.startsWith('data: ')) continue;
					const data = line.slice(6).trim();
					if (data === '[DONE]') break;
					try {
						const parsed = JSON.parse(data);
						const delta = parsed.choices?.[0]?.delta?.content;
						if (delta) {
							assistantContent += delta;
							const msgs = [...simState.chatMessages];
							msgs[msgs.length - 1] = { role: 'assistant', content: assistantContent };
							simState.chatMessages = msgs;
						}
					} catch { /* skip malformed chunks */ }
				}
			}
		} catch (e) {
			simState.chatMessages = [...simState.chatMessages, { role: 'assistant', content: `Connection error: ${e}` }];
		}
		chatLoading = false;
	}

	function fmt(n: number) { return `$${(n / 100).toFixed(2)}`; }
	function ms(n: number) { return n < 1 ? `${(n * 1000).toFixed(0)}μs` : n < 100 ? `${n.toFixed(2)}ms` : `${n.toFixed(0)}ms`; }

	// View mode for split panel (MiroFish pattern)
	let viewMode = $state<'graph' | 'split' | 'workbench'>('split');

	function goToStep(step: SimStep) {
		simState.step = step;
	}

	// Step 1: Seed data
	async function loadSeedData() {
		simState.addLog('Loading seed data and generating ontology...');
		// Generate demo graph data for now
		const demo = generateDemoGraph();
		simState.graphNodes = demo.nodes;
		simState.graphEdges = demo.edges;
		simState.addLog(`Generated ${demo.nodes.length} entities and ${demo.edges.length} relationships`);
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
			const res = await fetch(`${ENGINE}/products`);
			const products = await res.json();
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
			const protocols = ['acp', 'x402', 'ap2', 'mpp', 'atxp'];
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
					protocol_preference: Math.random() < 0.3 ? protocols[Math.floor(Math.random() * protocols.length)] : null,
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
		simState.addLog('Starting simulation...');

		try {
			const res = await fetch('/api/simulate', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					agents: simState.config.num_agents,
					rounds: simState.config.num_rounds,
				}),
			});

			const reader = res.body?.getReader();
			const dec = new TextDecoder();
			let buf = '';

			while (reader) {
				const { done, value } = await reader.read();
				if (done) break;
				buf += dec.decode(value, { stream: true });
				const lines = buf.split('\n');
				buf = lines.pop() || '';

				for (const l of lines) {
					if (!l.trim()) continue;
					try {
						const ev = JSON.parse(l);
						simState.events = [...simState.events, ev];
						simState.addLog(`[${ev.type}] ${ev.agent || ''} ${ev.product || ''} ${ev.protocol || ''}`);

						if (ev.type === 'simulation_complete') {
							simState.complete = true;
							simState.elapsed = `${ev.duration_seconds}s`;
							simState.totalTxns = ev.total_transactions;
							simState.totalVolume = ev.total_volume_cents;
							simState.metrics = Object.values(ev.protocol_summaries as Record<string, unknown>)
								.sort((a: any, b: any) => a.avg_settlement_ms - b.avg_settlement_ms) as any[];

							// Add transaction edges to graph
							const txEdges = simState.purchases.slice(0, 20).map((p: any) => ({
								source: p.agent,
								target: `merchant_${(p.protocol as string)}`,
								label: `${p.protocol} ${fmt(p.amount_cents)}`,
							}));
							const merchantNodes = simState.config.protocols.map(p => ({
								id: `merchant_${p}`, name: `${p.toUpperCase()} Merchant`, type: 'Merchant',
							}));
							simState.graphNodes = [...simState.graphNodes, ...merchantNodes];
							simState.graphEdges = [...simState.graphEdges, ...txEdges];
						}
					} catch { /* skip */ }
				}
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
				content: `Simulation completed with ${simState.totalTxns} transactions across 5 protocols. Total volume: ${fmt(simState.totalVolume)}. Duration: ${simState.elapsed}.`,
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
		];
		simState.step = 'report';
	}
</script>

<div style="display:flex; flex-direction:column; height:calc(100vh - 56px - 56px);">
	<!-- Step bar (MiroFish header pattern) -->
	<div style="
		padding:8px 24px;
		border-bottom:1px solid var(--bd);
		background:var(--bg-1);
		display:flex;
		align-items:center;
		justify-content:space-between;
	">
		<StepIndicator currentStep={simState.step} onStepClick={goToStep} />

		<!-- View mode switcher (MiroFish pattern) -->
		<div style="display:flex; gap:2px; background:var(--bg-2); padding:3px; border-radius:6px;">
			{#each [
				{ key: 'graph', label: 'Graph' },
				{ key: 'split', label: 'Split' },
				{ key: 'workbench', label: 'Workbench' },
			] as mode}
				<button
					onclick={() => viewMode = mode.key as any}
					style="
						font-size:11px; font-weight:600; padding:4px 12px; border:none;
						border-radius:4px; cursor:pointer;
						background:{viewMode === mode.key ? 'var(--bg-4)' : 'transparent'};
						color:{viewMode === mode.key ? 'var(--tx-1)' : 'var(--tx-3)'};
					"
				>{mode.label}</button>
			{/each}
		</div>
	</div>

	<!-- Main content: split view -->
	<div style="flex:1; display:flex; overflow:hidden;">
		<!-- Left: Graph panel -->
		{#if viewMode !== 'workbench'}
			<div style="
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
			<div style="
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
								Seed Data
							</h2>
							<p style="font-size:12px; color:var(--tx-3); margin-bottom:20px;">Upload market description or use demo data to build the commerce knowledge graph.</p>

							<textarea
								bind:value={simState.seedText}
								placeholder="Describe the market scenario...&#10;&#10;Example: An online marketplace with electronics, fashion, and food vendors. 50 buyer agents with diverse budgets ($50-$500) comparing prices across 5 payment protocols..."
								style="
									width:100%; min-height:180px; padding:16px;
									background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
									color:var(--tx-1); font-family:var(--sans); font-size:13px;
									line-height:1.6; resize:vertical;
								"
							></textarea>

							<div style="display:flex; gap:10px; margin-top:16px;">
								<button onclick={loadSeedData} style="
									padding:10px 24px; border:none; border-radius:4px;
									background:var(--acp); color:#fff; font-weight:600; font-size:13px;
								">Build Knowledge Graph</button>
								<button onclick={() => { const d = generateDemoGraph(); simState.graphNodes = d.nodes; simState.graphEdges = d.edges; simState.step = 'graph'; }} style="
									padding:10px 24px; border:1px solid var(--bd); border-radius:4px;
									background:transparent; color:var(--tx-2); font-weight:600; font-size:13px;
								">Use Demo Data</button>
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

							<div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:8px; margin-bottom:20px;">
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
								<label style="display:flex; flex-direction:column; gap:2px;">
									<span style="font-size:8px; font-weight:600; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em;">Agents</span>
									<input type="number" bind:value={simState.config.num_agents} min="10" max="1000" style="
										width:60px; background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
										padding:5px 8px; color:var(--tx-1); font-family:var(--mono); font-size:12px;
									" />
								</label>
								<label style="display:flex; flex-direction:column; gap:2px;">
									<span style="font-size:8px; font-weight:600; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em;">Rounds</span>
									<input type="number" bind:value={simState.config.num_rounds} min="1" max="100" style="
										width:60px; background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
										padding:5px 8px; color:var(--tx-1); font-family:var(--mono); font-size:12px;
									" />
								</label>
								<label style="display:flex; flex-direction:column; gap:2px;">
									<span style="font-size:8px; font-weight:600; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em;">Seed</span>
									<input type="number" bind:value={simState.config.seed} style="
										width:60px; background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
										padding:5px 8px; color:var(--tx-1); font-family:var(--mono); font-size:12px;
									" />
								</label>
							</div>

							<!-- Agent cards grid -->
							<div style="display:grid; grid-template-columns:repeat(2, 1fr); gap:8px; max-height:400px; overflow-y:auto;">
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
								<div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:1px; background:var(--bd); border-radius:6px; overflow:hidden; margin:16px 0;">
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

								<button onclick={generateReport} style="
									padding:10px 24px; border:none; border-radius:4px;
									background:var(--acp); color:#fff; font-weight:600; font-size:13px;
								">Generate Report →</button>
							{/if}

							<!-- Timeline -->
							<div style="margin-top:16px;">
								<Timeline events={simState.purchases.slice(-40)} />
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
									<p style="font-size:13px; color:var(--tx-2); line-height:1.6;">{section.content}</p>
								</div>
							{/each}

							<button onclick={() => simState.step = 'chat'} style="
								padding:10px 24px; border:none; border-radius:4px; margin-top:8px;
								background:var(--acp); color:#fff; font-weight:600; font-size:13px;
							">Deep Interaction →</button>
						</div>

					{:else if simState.step === 'chat'}
						<!-- Step 6: Chat -->
						<div style="display:flex; flex-direction:column; height:100%;">
							<h2 style="font-size:16px; font-weight:600; margin-bottom:12px;">
								<span style="font-family:var(--mono); color:var(--acp); margin-right:8px;">06</span>
								Deep Interaction
							</h2>

							{#if simState.metrics.length > 0}
								<div style="margin-bottom:12px;">
									<MarketCharts metrics={simState.metrics} />
								</div>
							{/if}

							<div style="flex:1; min-height:0;">
								<ChatPanel
									messages={simState.chatMessages.map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }))}
									onSend={handleChatSend}
									disabled={chatLoading}
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
