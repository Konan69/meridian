<script lang="ts">
	import { onMount } from 'svelte';

	const ENGINE = 'http://localhost:4080';
	const PROTOCOL_META: Record<string, { color: string; label: string; desc: string }> = {
		acp: { color: '#3b82f6', label: 'ACP', desc: 'Shared Payment Tokens · Card Rails' },
		ap2: { color: '#ef4444', label: 'AP2', desc: 'Verifiable Digital Credentials · Multi-Rail' },
		x402: { color: '#10b981', label: 'x402', desc: 'HTTP 402 · USDC On-Chain' },
		mpp: { color: '#8b5cf6', label: 'MPP', desc: 'Session Streaming · Multi-Rail' },
		atxp: { color: '#f59e0b', label: 'ATXP', desc: 'Mandate Engine · Agent-to-Agent' }
	};

	interface SimEvent { type: string; [key: string]: unknown; }
	interface ProtoMetrics {
		protocol: string; total_transactions: number; successful_transactions: number;
		failed_transactions: number; total_volume_cents: number; total_fees_cents: number;
		avg_settlement_ms: number; micropayment_count: number;
	}

	let events = $state<SimEvent[]>([]);
	let running = $state(false);
	let complete = $state(false);
	let finalMetrics = $state<ProtoMetrics[]>([]);
	let numAgents = $state(50);
	let numRounds = $state(10);
	let elapsed = $state('0.0s');
	let totalTxns = $state(0);
	let totalVolume = $state(0);

	function cents(n: number) { return `$${(n / 100).toFixed(2)}`; }

	let purchases = $derived(events.filter(e => e.type === 'purchase'));
	let failures = $derived(events.filter(e => e.type === 'purchase_failed'));
	let roundEvents = $derived(events.filter(e => e.type === 'round_complete'));

	async function runSimulation() {
		events = [];
		running = true;
		complete = false;
		finalMetrics = [];
		totalTxns = 0;
		totalVolume = 0;

		try {
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
							elapsed = `${event.duration_seconds}s`;
							totalTxns = event.total_transactions as number;
							totalVolume = event.total_volume_cents as number;
							const summaries = event.protocol_summaries as Record<string, ProtoMetrics>;
							finalMetrics = Object.values(summaries).sort(
								(a, b) => a.avg_settlement_ms - b.avg_settlement_ms
							);
						}
					} catch { /* skip */ }
				}
			}
		} catch (e) {
			events = [...events, { type: 'error', message: String(e) }];
		} finally {
			running = false;
		}
	}
</script>

<div class="sim-page">
	<!-- Header -->
	<div class="sim-header">
		<div class="sim-title-group">
			<h1 class="sim-title">Simulation</h1>
			<p class="sim-subtitle">Protocol comparison across flat agent distribution</p>
		</div>
		<div class="sim-controls">
			<div class="control-field">
				<label class="control-label">AGENTS</label>
				<input type="number" bind:value={numAgents} min="10" max="1000" class="control-input" />
			</div>
			<div class="control-field">
				<label class="control-label">ROUNDS</label>
				<input type="number" bind:value={numRounds} min="1" max="100" class="control-input" />
			</div>
			<button onclick={runSimulation} disabled={running} class="run-btn" class:running>
				{#if running}
					<span class="spinner"></span>
					Running...
				{:else}
					Run Simulation
				{/if}
			</button>
		</div>
	</div>

	{#if complete}
		<!-- Summary bar -->
		<div class="summary-bar">
			<div class="summary-stat">
				<span class="summary-value">{totalTxns}</span>
				<span class="summary-label">TRANSACTIONS</span>
			</div>
			<div class="summary-stat">
				<span class="summary-value">{cents(totalVolume)}</span>
				<span class="summary-label">VOLUME</span>
			</div>
			<div class="summary-stat">
				<span class="summary-value">{elapsed}</span>
				<span class="summary-label">DURATION</span>
			</div>
			<div class="summary-stat">
				<span class="summary-value">{numAgents}</span>
				<span class="summary-label">AGENTS</span>
			</div>
		</div>

		<!-- Protocol comparison -->
		<div class="proto-grid">
			{#each finalMetrics as p}
				{@const meta = PROTOCOL_META[p.protocol]}
				{@const vol = p.total_volume_cents}
				{@const fees = p.total_fees_cents}
				{@const feePct = vol > 0 ? ((fees / vol) * 100).toFixed(2) : '0.00'}
				<div class="proto-card" style="--proto-color: {meta?.color ?? '#888'}">
					<div class="proto-card-header">
						<span class="proto-dot"></span>
						<span class="proto-name">{meta?.label ?? p.protocol}</span>
						<span class="proto-exec">{p.avg_settlement_ms.toFixed(3)}ms</span>
					</div>
					<p class="proto-desc">{meta?.desc ?? ''}</p>
					<div class="proto-stats">
						<div class="proto-stat-row">
							<span class="proto-stat-label">Transactions</span>
							<span class="proto-stat-value">{p.successful_transactions}<span class="proto-stat-dim">/{p.total_transactions}</span></span>
						</div>
						<div class="proto-stat-row">
							<span class="proto-stat-label">Volume</span>
							<span class="proto-stat-value">{cents(vol)}</span>
						</div>
						<div class="proto-stat-row">
							<span class="proto-stat-label">Fees</span>
							<span class="proto-stat-value">{cents(fees)} <span class="proto-stat-dim">({feePct}%)</span></span>
						</div>
						<div class="proto-stat-row">
							<span class="proto-stat-label">Failed</span>
							<span class="proto-stat-value" class:has-failures={p.failed_transactions > 0}>{p.failed_transactions}</span>
						</div>
						<div class="proto-stat-row">
							<span class="proto-stat-label">Micropayments</span>
							<span class="proto-stat-value">{p.micropayment_count}</span>
						</div>
					</div>
					<!-- Execution bar -->
					<div class="exec-bar-container">
						<div class="exec-bar" style="width: {Math.min((p.avg_settlement_ms / (finalMetrics[finalMetrics.length - 1]?.avg_settlement_ms || 1)) * 100, 100)}%"></div>
					</div>
				</div>
			{/each}
		</div>
	{/if}

	<!-- Live feed grid -->
	<div class="feed-grid">
		<!-- Round progress -->
		<div class="feed-panel">
			<div class="feed-panel-header">
				<span class="feed-panel-icon">
					<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
						<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
					</svg>
				</span>
				<span class="feed-panel-title">Round Progress</span>
				<span class="feed-panel-count">{roundEvents.length}/{numRounds}</span>
			</div>
			<div class="feed-panel-body">
				{#each roundEvents as rd}
					{@const r = rd as Record<string, unknown>}
					<div class="round-row">
						<span class="round-label">R{r.round}</span>
						<div class="round-bar-track">
							<div class="round-bar-fill" style="width: {((r.round as number) / numRounds) * 100}%"></div>
						</div>
						<span class="round-stats">
							{r.success} ok · {r.failed} fail · {cents(r.volume_cents as number)}
						</span>
					</div>
				{/each}
				{#if running && roundEvents.length === 0}
					<div class="feed-waiting"><span class="spinner-small"></span> Waiting for first round...</div>
				{/if}
			</div>
		</div>

		<!-- Live transactions -->
		<div class="feed-panel">
			<div class="feed-panel-header">
				<span class="feed-panel-icon">
					<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
						<path d="M12 2v20M2 12h20"></path>
					</svg>
				</span>
				<span class="feed-panel-title">Live Transactions</span>
				<span class="feed-panel-count">{purchases.length}</span>
			</div>
			<div class="feed-panel-body tx-feed">
				{#each purchases.slice(-60) as tx}
					{@const t = tx as Record<string, unknown>}
					{@const proto = t.protocol as string}
					<div class="tx-row">
						<span class="tx-dot" style="background: {PROTOCOL_META[proto]?.color ?? '#888'}"></span>
						<span class="tx-round">R{t.round}</span>
						<span class="tx-agent">{t.agent}</span>
						<span class="tx-arrow">→</span>
						<span class="tx-product">{t.product}</span>
						<span class="tx-amount">{cents(t.amount_cents as number)}</span>
						<span class="tx-proto" style="color: {PROTOCOL_META[proto]?.color}">{proto.toUpperCase()}</span>
						{#if t.fee_cents}
							<span class="tx-fee">fee {cents(t.fee_cents as number)}</span>
						{/if}
					</div>
				{/each}
				{#if running && purchases.length === 0}
					<div class="feed-waiting"><span class="spinner-small"></span> Waiting for purchases...</div>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.sim-page {
		max-width: 1200px;
		margin: 0 auto;
		font-family: 'Inter', 'Space Grotesk', system-ui, sans-serif;
	}

	/* Header */
	.sim-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 24px;
	}
	.sim-title {
		font-size: 20px;
		font-weight: 600;
		letter-spacing: -0.02em;
		color: var(--color-text-primary, #f0f0f5);
	}
	.sim-subtitle {
		font-size: 12px;
		color: var(--color-text-muted, #55556a);
		margin-top: 2px;
	}
	.sim-controls {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.control-field {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.control-label {
		font-size: 8px;
		font-weight: 600;
		color: var(--color-text-muted, #55556a);
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}
	.control-input {
		width: 64px;
		background: var(--color-surface-2, #1a1a24);
		border: 1px solid var(--color-border, #2a2a38);
		border-radius: 4px;
		padding: 6px 8px;
		color: var(--color-text-primary, #f0f0f5);
		font-family: 'JetBrains Mono', monospace;
		font-size: 12px;
	}
	.control-input:focus {
		outline: none;
		border-color: var(--color-border-active, #3b82f6);
	}
	.run-btn {
		padding: 8px 20px;
		border-radius: 4px;
		border: none;
		font-size: 12px;
		font-weight: 600;
		letter-spacing: 0.02em;
		cursor: pointer;
		transition: all 0.2s;
		background: #3b82f6;
		color: #fff;
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.run-btn:hover:not(:disabled) { background: #2563eb; }
	.run-btn:disabled { opacity: 0.5; cursor: not-allowed; }
	.run-btn.running { background: var(--color-surface-3, #22222e); color: var(--color-text-muted); }

	/* Spinner */
	.spinner, .spinner-small {
		display: inline-block;
		border: 2px solid transparent;
		border-top-color: currentColor;
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}
	.spinner { width: 14px; height: 14px; }
	.spinner-small { width: 10px; height: 10px; border-width: 1.5px; }
	@keyframes spin { to { transform: rotate(360deg); } }

	/* Summary bar */
	.summary-bar {
		display: flex;
		gap: 1px;
		background: var(--color-border, #2a2a38);
		border-radius: 4px;
		overflow: hidden;
		margin-bottom: 20px;
	}
	.summary-stat {
		flex: 1;
		background: var(--color-surface-1, #12121a);
		padding: 12px 16px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
	}
	.summary-value {
		font-family: 'JetBrains Mono', monospace;
		font-size: 18px;
		font-weight: 700;
		color: var(--color-text-primary);
	}
	.summary-label {
		font-size: 8px;
		font-weight: 600;
		color: var(--color-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}

	/* Protocol cards grid */
	.proto-grid {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: 8px;
		margin-bottom: 20px;
	}
	.proto-card {
		background: var(--color-surface-1, #12121a);
		border: 1px solid var(--color-border, #2a2a38);
		border-radius: 4px;
		padding: 14px;
		transition: border-color 0.2s;
	}
	.proto-card:hover {
		border-color: var(--proto-color);
	}
	.proto-card-header {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 4px;
	}
	.proto-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--proto-color);
	}
	.proto-name {
		font-size: 12px;
		font-weight: 700;
		color: var(--proto-color);
		font-family: 'JetBrains Mono', monospace;
		letter-spacing: 0.03em;
	}
	.proto-exec {
		margin-left: auto;
		font-size: 10px;
		font-family: 'JetBrains Mono', monospace;
		color: var(--color-text-muted);
	}
	.proto-desc {
		font-size: 9px;
		color: var(--color-text-muted);
		margin-bottom: 10px;
		line-height: 1.3;
	}
	.proto-stats {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.proto-stat-row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		font-size: 11px;
	}
	.proto-stat-label {
		color: var(--color-text-muted);
	}
	.proto-stat-value {
		font-family: 'JetBrains Mono', monospace;
		font-weight: 500;
		color: var(--color-text-primary);
	}
	.proto-stat-dim {
		color: var(--color-text-muted);
		font-weight: 400;
	}
	.has-failures {
		color: #ef4444;
	}
	.exec-bar-container {
		margin-top: 10px;
		height: 3px;
		background: var(--color-surface-0, #0a0a0f);
		border-radius: 2px;
		overflow: hidden;
	}
	.exec-bar {
		height: 100%;
		background: var(--proto-color);
		border-radius: 2px;
		transition: width 0.5s ease;
	}

	/* Feed grid */
	.feed-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 12px;
	}
	.feed-panel {
		background: var(--color-surface-1, #12121a);
		border: 1px solid var(--color-border, #2a2a38);
		border-radius: 4px;
		overflow: hidden;
	}
	.feed-panel-header {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 10px 14px;
		border-bottom: 1px solid var(--color-border, #2a2a38);
		background: var(--color-surface-2, #1a1a24);
	}
	.feed-panel-icon {
		color: var(--color-text-muted);
	}
	.feed-panel-title {
		font-size: 11px;
		font-weight: 600;
		color: var(--color-text-secondary, #8888a0);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.feed-panel-count {
		margin-left: auto;
		font-size: 10px;
		font-family: 'JetBrains Mono', monospace;
		color: var(--color-text-muted);
	}
	.feed-panel-body {
		padding: 8px;
		max-height: 360px;
		overflow-y: auto;
	}
	.feed-waiting {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 16px;
		color: var(--color-text-muted);
		font-size: 12px;
	}

	/* Round rows */
	.round-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 6px;
		font-size: 11px;
	}
	.round-label {
		font-family: 'JetBrains Mono', monospace;
		color: var(--color-text-muted);
		width: 28px;
		text-align: right;
		font-size: 10px;
	}
	.round-bar-track {
		flex: 1;
		height: 4px;
		background: var(--color-surface-0, #0a0a0f);
		border-radius: 2px;
		overflow: hidden;
	}
	.round-bar-fill {
		height: 100%;
		background: #3b82f6;
		border-radius: 2px;
		transition: width 0.3s ease;
	}
	.round-stats {
		font-family: 'JetBrains Mono', monospace;
		color: var(--color-text-secondary);
		font-size: 10px;
		white-space: nowrap;
		min-width: 140px;
		text-align: right;
	}

	/* Transaction rows */
	.tx-feed {
		font-family: 'JetBrains Mono', monospace;
		font-size: 10px;
	}
	.tx-row {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: 3px 6px;
		border-bottom: 1px solid var(--color-surface-2, #1a1a24);
		transition: background 0.15s;
	}
	.tx-row:hover {
		background: var(--color-surface-2, #1a1a24);
	}
	.tx-dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.tx-round {
		color: var(--color-text-muted);
		width: 24px;
	}
	.tx-agent {
		color: var(--color-text-secondary);
		width: 80px;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.tx-arrow {
		color: var(--color-text-muted);
	}
	.tx-product {
		flex: 1;
		color: var(--color-text-secondary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.tx-amount {
		color: #f59e0b;
		font-weight: 600;
		white-space: nowrap;
	}
	.tx-proto {
		font-weight: 700;
		font-size: 9px;
		width: 36px;
		text-align: right;
	}
	.tx-fee {
		color: var(--color-text-muted);
		font-size: 9px;
		white-space: nowrap;
	}

	/* Scrollbar styling */
	.feed-panel-body::-webkit-scrollbar {
		width: 4px;
	}
	.feed-panel-body::-webkit-scrollbar-track {
		background: transparent;
	}
	.feed-panel-body::-webkit-scrollbar-thumb {
		background: var(--color-surface-3, #22222e);
		border-radius: 2px;
	}
</style>
