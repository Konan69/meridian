<script lang="ts">
	import { onMount } from 'svelte';

	const ENGINE = 'http://localhost:4080';
	const COLORS: Record<string, string> = {
		acp: '#3b82f6', ap2: '#ef4444', x402: '#10b981', mpp: '#8b5cf6', atxp: '#f59e0b'
	};

	interface SimEvent {
		type: string;
		[key: string]: unknown;
	}

	let events = $state<SimEvent[]>([]);
	let running = $state(false);
	let complete = $state(false);
	let finalMetrics = $state<Record<string, unknown>[]>([]);

	// Config
	let numAgents = $state(50);
	let numRounds = $state(10);

	function cents(n: number) {
		return `$${(n / 100).toFixed(2)}`;
	}

	async function runSimulation() {
		events = [];
		running = true;
		complete = false;
		finalMetrics = [];

		try {
			// Call the Python sim via a local API endpoint
			const res = await fetch('/api/simulate', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ agents: numAgents, rounds: numRounds })
			});

			const reader = res.body?.getReader();
			const decoder = new TextDecoder();
			let buffer = '';

			while (reader) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split('\n');
				buffer = lines.pop() || '';

				for (const line of lines) {
					if (!line.trim()) continue;
					try {
						const event: SimEvent = JSON.parse(line);
						events = [...events, event];

						if (event.type === 'simulation_complete') {
							complete = true;
							const summaries = event.protocol_summaries as Record<string, unknown>;
							finalMetrics = Object.values(summaries);
						}
					} catch { /* skip bad lines */ }
				}
			}
		} catch (e) {
			events = [...events, { type: 'error', message: String(e) }];
		} finally {
			running = false;
		}
	}

	let purchases = $derived(events.filter(e => e.type === 'purchase'));
	let roundEvents = $derived(events.filter(e => e.type === 'round_complete'));
</script>

<div class="max-w-6xl mx-auto space-y-6">
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-semibold">Run Simulation</h1>

		<div class="flex items-center gap-4">
			<label class="flex items-center gap-2 text-sm">
				<span class="text-text-muted">Agents:</span>
				<input
					type="number"
					bind:value={numAgents}
					min="10"
					max="1000"
					class="w-20 bg-surface-2 border border-border rounded px-2 py-1 text-sm font-mono"
				/>
			</label>
			<label class="flex items-center gap-2 text-sm">
				<span class="text-text-muted">Rounds:</span>
				<input
					type="number"
					bind:value={numRounds}
					min="1"
					max="100"
					class="w-20 bg-surface-2 border border-border rounded px-2 py-1 text-sm font-mono"
				/>
			</label>
			<button
				onclick={runSimulation}
				disabled={running}
				class="px-4 py-2 rounded-lg font-medium text-sm transition-all
					{running
						? 'bg-surface-3 text-text-muted cursor-not-allowed'
						: 'bg-blue-600 hover:bg-blue-500 text-white'}"
			>
				{running ? 'Running...' : 'Start Simulation'}
			</button>
		</div>
	</div>

	{#if complete && finalMetrics.length > 0}
		<!-- Protocol comparison results -->
		<div class="bg-surface-1 border border-border rounded-lg p-6">
			<h2 class="text-lg font-semibold mb-4">Protocol Comparison Results</h2>
			<div class="overflow-x-auto">
				<table class="w-full text-sm">
					<thead>
						<tr class="text-text-muted text-left border-b border-border">
							<th class="pb-2 pr-4">Protocol</th>
							<th class="pb-2 pr-4 text-right">Txns</th>
							<th class="pb-2 pr-4 text-right">Volume</th>
							<th class="pb-2 pr-4 text-right">Fees</th>
							<th class="pb-2 pr-4 text-right">Fee %</th>
							<th class="pb-2 pr-4 text-right">Settlement</th>
							<th class="pb-2 text-right">Micropay</th>
						</tr>
					</thead>
					<tbody>
						{#each finalMetrics.sort((a, b) => (a.avg_settlement_ms as number) - (b.avg_settlement_ms as number)) as p}
							{@const proto = p.protocol as string}
							{@const vol = p.total_volume_cents as number}
							{@const fees = p.total_fees_cents as number}
							<tr class="border-b border-border/50">
								<td class="py-2 pr-4">
									<span class="flex items-center gap-2">
										<span class="w-2.5 h-2.5 rounded-full" style="background-color: {COLORS[proto]}"></span>
										<span class="font-mono font-bold" style="color: {COLORS[proto]}">{proto.toUpperCase()}</span>
									</span>
								</td>
								<td class="py-2 pr-4 text-right font-mono">{p.total_transactions}</td>
								<td class="py-2 pr-4 text-right font-mono">{cents(vol)}</td>
								<td class="py-2 pr-4 text-right font-mono">{cents(fees)}</td>
								<td class="py-2 pr-4 text-right font-mono">{vol > 0 ? ((fees / vol) * 100).toFixed(2) : '0'}%</td>
								<td class="py-2 pr-4 text-right font-mono">{p.avg_settlement_ms}ms</td>
								<td class="py-2 text-right font-mono">{p.micropayment_count}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}

	<!-- Live event feed -->
	<div class="grid grid-cols-2 gap-6">
		<!-- Round progress -->
		<div class="bg-surface-1 border border-border rounded-lg p-4">
			<h3 class="text-sm font-semibold text-text-muted mb-3">Round Progress</h3>
			<div class="space-y-1.5 max-h-80 overflow-y-auto">
				{#each roundEvents as rd}
					{@const r = rd as Record<string, unknown>}
					<div class="flex items-center gap-2 text-sm">
						<span class="text-text-muted font-mono w-8">R{r.round}</span>
						<div class="flex-1 h-2 bg-surface-0 rounded-full overflow-hidden">
							<div
								class="h-full bg-blue-500 rounded-full transition-all"
								style="width: {((r.round as number) / numRounds) * 100}%"
							></div>
						</div>
						<span class="font-mono text-xs text-text-secondary">
							{r.success} ok · {cents(r.volume_cents as number)}
						</span>
					</div>
				{/each}
				{#if running && roundEvents.length === 0}
					<div class="text-text-muted text-sm animate-pulse">Waiting for first round...</div>
				{/if}
			</div>
		</div>

		<!-- Live purchase feed -->
		<div class="bg-surface-1 border border-border rounded-lg p-4">
			<h3 class="text-sm font-semibold text-text-muted mb-3">
				Live Transactions
				<span class="font-mono text-text-muted">({purchases.length})</span>
			</h3>
			<div class="space-y-1 max-h-80 overflow-y-auto text-xs font-mono">
				{#each purchases.slice(-50) as tx}
					{@const t = tx as Record<string, unknown>}
					<div class="flex items-center gap-2 py-0.5">
						<span class="w-1.5 h-1.5 rounded-full" style="background-color: {COLORS[t.protocol as string]}"></span>
						<span class="text-text-muted">R{t.round}</span>
						<span class="text-text-secondary truncate flex-1">{t.agent} → {t.product}</span>
						<span class="text-amber-400">{cents(t.amount_cents as number)}</span>
						<span style="color: {COLORS[t.protocol as string]}">{(t.protocol as string).toUpperCase()}</span>
					</div>
				{/each}
				{#if running && purchases.length === 0}
					<div class="text-text-muted animate-pulse">Waiting for purchases...</div>
				{/if}
			</div>
		</div>
	</div>
</div>
