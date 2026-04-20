<script lang="ts">
	import { onMount } from 'svelte';

	interface Proto {
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

	interface Product {
		id: string;
		name: string;
		description: string;
		base_price: number;
		category: string;
		available_quantity: number;
		requires_shipping: boolean;
	}
	interface Capabilities {
		supported_protocols: string[];
	}

	const ENGINE = 'http://localhost:4080';
	const COLORS: Record<string, string> = {
		acp: 'var(--acp)', ap2: 'var(--ap2)', x402: 'var(--x402)',
		mpp: 'var(--mpp)', atxp: 'var(--atxp)'
	};

	let protos = $state<Proto[]>([]);
	let products = $state<Product[]>([]);
	let online = $state(false);
	let loading = $state(true);
	let liveProtocolCount = $state(0);

	function fmt(n: number) { return `$${(n / 100).toFixed(2)}`; }
	function ms(n: number) { return n < 1 ? `${(n * 1000).toFixed(0)}μs` : n < 100 ? `${n.toFixed(2)}ms` : `${n.toFixed(0)}ms`; }
	function pct(a: number, b: number) { return b > 0 ? `${((a / b) * 100).toFixed(2)}%` : '—'; }

	async function refresh() {
		try {
			const [h, m, p, c] = await Promise.all([
				fetch(`${ENGINE}/health`),
				fetch(`${ENGINE}/metrics`),
				fetch(`${ENGINE}/products`),
				fetch(`${ENGINE}/capabilities`)
			]);
			online = h.ok;
			protos = ((await m.json()) as { protocols: Proto[] }).protocols
				.sort((a, b) => a.avg_settlement_ms - b.avg_settlement_ms);
			products = await p.json();
			const caps = await c.json() as Capabilities;
			liveProtocolCount = Array.isArray(caps.supported_protocols) ? caps.supported_protocols.length : protos.length;
		} catch { online = false; }
		loading = false;
	}

	onMount(() => { refresh(); const i = setInterval(refresh, 3000); return () => clearInterval(i); });
</script>

<div>
	<!-- Header row -->
	<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:28px;">
		<div>
			<h1 style="font-size:22px; font-weight:600; letter-spacing:-0.03em;">Protocol Comparison</h1>
			<p style="font-size:13px; color:var(--tx-3); margin-top:4px;">Real-time metrics across {liveProtocolCount || protos.length} live agentic commerce protocol{(liveProtocolCount || protos.length) === 1 ? '' : 's'}</p>
		</div>
		<div style="display:flex; align-items:center; gap:8px;">
			<span
				style="width:8px; height:8px; border-radius:50%; background:{online ? '#10b981' : '#ef4444'}; {online ? 'animation: pulse 2s infinite;' : ''}"
				aria-hidden="true"
			></span>
			<span style="font-family:var(--mono); font-size:11px; color:var(--tx-3);" aria-live="polite">
				Engine {online ? 'online' : 'offline'} · :4080
			</span>
		</div>
	</div>

	{#if loading}
		<div style="text-align:center; padding:80px 0; color:var(--tx-3); font-size:14px;">Loading...</div>
	{:else}
		<!-- Protocol cards -->
		<div class="protocol-grid" style="margin-bottom:32px;">
			{#each protos as p}
				{@const color = COLORS[p.protocol] ?? '#888'}
				{@const vol = p.total_volume_cents}
				{@const fees = p.total_fees_cents}
				{@const maxExec = protos[protos.length - 1]?.avg_settlement_ms || 1}
				<div role="article"
					style="
					background: var(--bg-1);
					border: 1px solid var(--bd);
					border-radius: 6px;
					padding: 18px;
					transition: border-color 0.2s;
				" onmouseenter={(e) => e.currentTarget.style.borderColor = color}
				   onmouseleave={(e) => e.currentTarget.style.borderColor = 'var(--bd)'}>

					<!-- Header -->
					<div style="display:flex; align-items:center; gap:6px; margin-bottom:6px;">
						<span style="width:8px; height:8px; border-radius:50%; background:{color};"></span>
						<span style="font-family:var(--mono); font-weight:700; font-size:13px; color:{color};">
							{p.protocol.toUpperCase()}
						</span>
						<span style="margin-left:auto; font-family:var(--mono); font-size:10px; color:var(--tx-3);">
							{ms(p.avg_settlement_ms)}
						</span>
					</div>

					<!-- Stats -->
					<div style="display:flex; flex-direction:column; gap:8px; margin-top:12px;">
						<div style="display:flex; justify-content:space-between; font-size:12px;">
							<span style="color:var(--tx-3);">Transactions</span>
							<span style="font-family:var(--mono); font-weight:500;">
								{p.successful_transactions}<span style="color:var(--tx-3);">/{p.total_transactions}</span>
							</span>
						</div>
						<div style="display:flex; justify-content:space-between; font-size:12px;">
							<span style="color:var(--tx-3);">Volume</span>
							<span style="font-family:var(--mono); font-weight:500;">{fmt(vol)}</span>
						</div>
						<div style="display:flex; justify-content:space-between; font-size:12px;">
							<span style="color:var(--tx-3);">Fees</span>
							<span style="font-family:var(--mono); font-weight:500;">
								{fmt(fees)} <span style="color:var(--tx-3);">({pct(fees, vol)})</span>
							</span>
						</div>
						<div style="display:flex; justify-content:space-between; font-size:12px;">
							<span style="color:var(--tx-3);">Micropayments</span>
							<span style="font-family:var(--mono); font-weight:500;">{p.micropayment_count}</span>
						</div>
					</div>

					<!-- Exec bar -->
					<div style="margin-top:14px;">
						<div style="height:3px; background:var(--bg-0); border-radius:2px; overflow:hidden;">
							<div style="
								height:100%;
								border-radius:2px;
								background:{color};
								width:{Math.min((p.avg_settlement_ms / maxExec) * 100, 100)}%;
								transition: width 0.5s ease;
							"></div>
						</div>
					</div>
				</div>
			{/each}
		</div>

		<!-- Product catalog -->
		<div>
			<h2 style="font-size:16px; font-weight:600; margin-bottom:14px; letter-spacing:-0.02em;">Product Catalog</h2>
			<div class="product-grid">
				{#each products as prod}
					<div style="
						background: var(--bg-1);
						border: 1px solid var(--bd);
						border-radius: 6px;
						padding: 16px;
					">
						<div style="display:flex; justify-content:space-between; align-items:flex-start;">
							<div>
								<div style="font-weight:500; font-size:14px;">{prod.name}</div>
								<div style="font-family:var(--mono); font-size:10px; color:var(--tx-3); margin-top:3px;">{prod.id}</div>
							</div>
							<span style="font-family:var(--mono); font-weight:600; font-size:14px; color:var(--atxp);">
								{fmt(prod.base_price)}
							</span>
						</div>
						<p style="font-size:12px; color:var(--tx-2); margin-top:8px; line-height:1.5;">{prod.description}</p>
						<div style="display:flex; align-items:center; gap:8px; margin-top:10px;">
							<span style="
								font-size:10px;
								padding:2px 8px;
								border-radius:2px;
								background:var(--bg-3);
								color:var(--tx-2);
								font-weight:500;
							">{prod.category}</span>
							<span style="font-size:10px; color:var(--tx-3);">
								{prod.available_quantity.toLocaleString()} in stock
							</span>
							{#if !prod.requires_shipping}
								<span style="font-size:10px; color:var(--x402); font-weight:500;">Digital</span>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</div>

<style>
	@keyframes pulse {
		50% { opacity: 0.4; }
	}
	.protocol-grid {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: 10px;
	}
	.product-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 10px;
	}
	@media (max-width: 1100px) {
		.protocol-grid { grid-template-columns: repeat(3, 1fr); }
	}
	@media (max-width: 768px) {
		.protocol-grid { grid-template-columns: repeat(2, 1fr); }
		.product-grid { grid-template-columns: repeat(2, 1fr); }
	}
	@media (max-width: 480px) {
		.protocol-grid { grid-template-columns: 1fr; }
		.product-grid { grid-template-columns: 1fr; }
	}
</style>
