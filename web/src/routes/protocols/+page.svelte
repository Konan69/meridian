<script lang="ts">
	import { onMount } from 'svelte';

	interface ProtocolMetrics {
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

	const ENGINE = 'http://localhost:4080';
	const COLORS: Record<string, string> = {
		acp: '#3b82f6',
		ap2: '#ef4444',
		x402: '#10b981',
		mpp: '#8b5cf6',
		atxp: '#f59e0b'
	};
	const DESCRIPTIONS: Record<string, string> = {
		acp: 'Shared Payment Tokens, card networks, BNPL. OpenAI + Stripe.',
		ap2: 'Verifiable Digital Credentials, Intent/Cart Mandates. Google.',
		x402: 'HTTP 402, USDC on-chain, stateless per-request. Coinbase.',
		mpp: 'HTTP 402 + sessions, streaming micropayments. Stripe + Tempo.',
		atxp: 'Mandate model, nested agent-to-agent transactions. Circuit & Chisel.'
	};

	let metrics = $state<ProtocolMetrics[]>([]);

	function cents(n: number) {
		return `$${(n / 100).toFixed(2)}`;
	}

	function pct(n: number, d: number) {
		return d > 0 ? `${((n / d) * 100).toFixed(2)}%` : '—';
	}

	async function refresh() {
		try {
			const res = await fetch(`${ENGINE}/metrics`);
			const data = await res.json();
			metrics = data.protocols.sort(
				(a: ProtocolMetrics, b: ProtocolMetrics) => a.avg_settlement_ms - b.avg_settlement_ms
			);
		} catch {
			/* engine offline */
		}
	}

	onMount(() => {
		refresh();
		const i = setInterval(refresh, 2000);
		return () => clearInterval(i);
	});
</script>

<div class="max-w-5xl mx-auto space-y-8">
	<h1 class="text-2xl font-semibold">Protocol Deep Dive</h1>

	{#each metrics as p}
		{@const color = COLORS[p.protocol] ?? '#888'}
		<div class="bg-surface-1 border border-border rounded-lg p-6 space-y-4">
			<div class="flex items-center justify-between">
				<div class="flex items-center gap-3">
					<span
						class="w-3 h-3 rounded-full"
						style="background-color: {color}"
					></span>
					<h2 class="text-xl font-mono font-bold" style="color: {color}">
						{p.protocol.toUpperCase()}
					</h2>
				</div>
				<span class="text-sm text-text-muted font-mono">
					{p.avg_settlement_ms}ms settlement · {p.avg_authorization_ms}ms auth
				</span>
			</div>

			<p class="text-sm text-text-secondary">{DESCRIPTIONS[p.protocol] ?? ''}</p>

			<div class="grid grid-cols-5 gap-4 text-center">
				<div class="bg-surface-2 rounded-lg p-3">
					<div class="text-2xl font-mono font-bold">{p.total_transactions}</div>
					<div class="text-xs text-text-muted mt-1">Transactions</div>
				</div>
				<div class="bg-surface-2 rounded-lg p-3">
					<div class="text-2xl font-mono font-bold">{cents(p.total_volume_cents)}</div>
					<div class="text-xs text-text-muted mt-1">Volume</div>
				</div>
				<div class="bg-surface-2 rounded-lg p-3">
					<div class="text-2xl font-mono font-bold">{cents(p.total_fees_cents)}</div>
					<div class="text-xs text-text-muted mt-1">Fees</div>
				</div>
				<div class="bg-surface-2 rounded-lg p-3">
					<div class="text-2xl font-mono font-bold">
						{pct(p.total_fees_cents, p.total_volume_cents)}
					</div>
					<div class="text-xs text-text-muted mt-1">Fee Rate</div>
				</div>
				<div class="bg-surface-2 rounded-lg p-3">
					<div class="text-2xl font-mono font-bold">{p.micropayment_count}</div>
					<div class="text-xs text-text-muted mt-1">Micropayments</div>
				</div>
			</div>

			<!-- Settlement bar -->
			<div>
				<div class="flex justify-between text-xs text-text-muted mb-1">
					<span>Settlement Latency</span>
					<span>{p.avg_settlement_ms}ms</span>
				</div>
				<div class="h-2 bg-surface-0 rounded-full overflow-hidden">
					<div
						class="h-full rounded-full transition-all duration-500"
						style="width: {Math.min((p.avg_settlement_ms / 3000) * 100, 100)}%; background-color: {color}"
					></div>
				</div>
			</div>
		</div>
	{/each}
</div>
