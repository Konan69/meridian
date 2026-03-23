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
		refund_count: number;
	}

	interface Product {
		id: string;
		name: string;
		base_price: number;
		category: string;
		available_quantity: number;
	}

	const ENGINE_URL = 'http://localhost:4080';
	const PROTOCOL_COLORS: Record<string, string> = {
		acp: 'text-protocol-acp',
		ap2: 'text-protocol-ap2',
		x402: 'text-protocol-x402',
		mpp: 'text-protocol-mpp',
		atxp: 'text-protocol-atxp'
	};
	const PROTOCOL_BG: Record<string, string> = {
		acp: 'bg-protocol-acp/10 border-protocol-acp/20',
		ap2: 'bg-protocol-ap2/10 border-protocol-ap2/20',
		x402: 'bg-protocol-x402/10 border-protocol-x402/20',
		mpp: 'bg-protocol-mpp/10 border-protocol-mpp/20',
		atxp: 'bg-protocol-atxp/10 border-protocol-atxp/20'
	};

	let metrics = $state<ProtocolMetrics[]>([]);
	let products = $state<Product[]>([]);
	let engineOnline = $state(false);
	let loading = $state(true);

	function cents(amount: number): string {
		return `$${(amount / 100).toFixed(2)}`;
	}

	async function fetchData() {
		try {
			const [healthRes, metricsRes, productsRes] = await Promise.all([
				fetch(`${ENGINE_URL}/health`),
				fetch(`${ENGINE_URL}/metrics`),
				fetch(`${ENGINE_URL}/products`)
			]);
			engineOnline = healthRes.ok;
			const metricsData = await metricsRes.json();
			metrics = metricsData.protocols;
			products = await productsRes.json();
		} catch {
			engineOnline = false;
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		fetchData();
		const interval = setInterval(fetchData, 3000);
		return () => clearInterval(interval);
	});
</script>

<div class="max-w-7xl mx-auto space-y-8">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-2xl font-semibold tracking-tight">Protocol Comparison Dashboard</h1>
			<p class="text-text-secondary text-sm mt-1">
				Real-time metrics across 5 agentic commerce protocols
			</p>
		</div>
		<div class="flex items-center gap-2">
			<span
				class="w-2 h-2 rounded-full {engineOnline ? 'bg-green-500 animate-pulse' : 'bg-red-500'}"
			></span>
			<span class="text-xs font-mono text-text-muted">
				Engine {engineOnline ? 'online' : 'offline'} · :4080
			</span>
		</div>
	</div>

	{#if loading}
		<div class="text-center py-20 text-text-muted">Loading...</div>
	{:else}
		<!-- Protocol cards grid -->
		<div class="grid grid-cols-5 gap-4">
			{#each metrics as proto}
				<div
					class="border rounded-lg p-4 space-y-3 {PROTOCOL_BG[proto.protocol] ?? 'bg-surface-1 border-border'}"
				>
					<div class="flex items-center justify-between">
						<span class="font-mono font-semibold {PROTOCOL_COLORS[proto.protocol] ?? ''}">
							{proto.protocol.toUpperCase()}
						</span>
						<span class="text-xs font-mono text-text-muted">
							{proto.avg_settlement_ms}ms
						</span>
					</div>

					<div class="space-y-2 text-sm">
						<div class="flex justify-between">
							<span class="text-text-muted">Transactions</span>
							<span class="font-mono">{proto.total_transactions}</span>
						</div>
						<div class="flex justify-between">
							<span class="text-text-muted">Volume</span>
							<span class="font-mono">{cents(proto.total_volume_cents)}</span>
						</div>
						<div class="flex justify-between">
							<span class="text-text-muted">Fees</span>
							<span class="font-mono">{cents(proto.total_fees_cents)}</span>
						</div>
						<div class="flex justify-between">
							<span class="text-text-muted">Success Rate</span>
							<span class="font-mono">
								{proto.total_transactions > 0
									? ((proto.successful_transactions / proto.total_transactions) * 100).toFixed(1)
									: '—'}%
							</span>
						</div>
						<div class="flex justify-between">
							<span class="text-text-muted">Micropayments</span>
							<span class="font-mono">{proto.micropayment_count}</span>
						</div>
					</div>

					<!-- Settlement bar -->
					<div class="pt-2">
						<div class="text-xs text-text-muted mb-1">Settlement Latency</div>
						<div class="h-1.5 bg-surface-0 rounded-full overflow-hidden">
							<div
								class="h-full rounded-full {proto.protocol === 'x402'
									? 'bg-protocol-x402'
									: proto.protocol === 'atxp'
										? 'bg-protocol-atxp'
										: proto.protocol === 'mpp'
											? 'bg-protocol-mpp'
											: proto.protocol === 'ap2'
												? 'bg-protocol-ap2'
												: 'bg-protocol-acp'}"
								style="width: {Math.min((proto.avg_settlement_ms / 3000) * 100, 100)}%"
							></div>
						</div>
					</div>
				</div>
			{/each}
		</div>

		<!-- Product catalog -->
		<div>
			<h2 class="text-lg font-semibold mb-3">Product Catalog</h2>
			<div class="grid grid-cols-3 gap-3">
				{#each products as product}
					<div class="bg-surface-1 border border-border rounded-lg p-4">
						<div class="flex justify-between items-start">
							<div>
								<div class="font-medium">{product.name}</div>
								<div class="text-xs text-text-muted font-mono mt-1">{product.id}</div>
							</div>
							<span class="text-amber-500 font-mono font-semibold">
								{cents(product.base_price)}
							</span>
						</div>
						<div class="flex items-center gap-2 mt-3">
							<span
								class="text-xs px-2 py-0.5 rounded bg-surface-2 text-text-secondary"
							>
								{product.category}
							</span>
							<span class="text-xs text-text-muted">
								{product.available_quantity} in stock
							</span>
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</div>
