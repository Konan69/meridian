<script lang="ts">
	import { onMount } from 'svelte';

	interface PM {
		protocol: string; total_transactions: number; successful_transactions: number;
		failed_transactions: number; total_volume_cents: number; total_fees_cents: number;
		avg_settlement_ms: number; avg_authorization_ms: number; micropayment_count: number;
	}

	const ENGINE = 'http://localhost:4080';
	const META: Record<string, { color: string; desc: string; stack: string; fee: string }> = {
		acp: { color:'var(--acp)', desc:'Shared Payment Tokens scoped to merchant/amount/time. Settlement via card networks.', stack:'OpenAI + Stripe', fee:'2.9% + 30¢' },
		ap2: { color:'var(--ap2)', desc:'Verifiable Digital Credentials with Intent/Cart Mandates. Double ECDSA signing.', stack:'Google', fee:'2.5% + 20¢' },
		x402: { color:'var(--x402)', desc:'HTTP 402 stateless payments. USDC on-chain via facilitator. ECDSA sign+verify per tx.', stack:'Coinbase', fee:'0.1%' },
		mpp: { color:'var(--mpp)', desc:'Session-based streaming micropayments. Bridges crypto and fiat. ECDSA receipt signing.', stack:'Stripe + Tempo', fee:'1.5% + 5¢' },
		atxp: { color:'var(--atxp)', desc:'Mandate engine with constraint validation. Multi-use budgets. Agent-to-agent nesting.', stack:'Circuit & Chisel', fee:'0.5%' },
	};

	let protos = $state<PM[]>([]);
	function fmt(n: number) { return `$${(n / 100).toFixed(2)}`; }
	function ms(n: number) { return n < 1 ? `${(n * 1000).toFixed(0)}μs` : n < 100 ? `${n.toFixed(2)}ms` : `${n.toFixed(0)}ms`; }

	async function refresh() {
		try {
			const r = await fetch(`${ENGINE}/metrics`);
			const d = await r.json();
			protos = d.protocols.sort((a: PM, b: PM) => a.avg_settlement_ms - b.avg_settlement_ms);
		} catch {}
	}

	onMount(() => { refresh(); const i = setInterval(refresh, 2000); return () => clearInterval(i); });
</script>

<div>
	<h1 style="font-size:22px; font-weight:600; letter-spacing:-0.03em; margin-bottom:24px;">Protocol Deep Dive</h1>

	<div style="display:flex; flex-direction:column; gap:14px;">
		{#each protos as p}
			{@const m = META[p.protocol]}
			{@const c = m?.color ?? '#888'}
			{@const v = p.total_volume_cents}
			{@const f = p.total_fees_cents}
			{@const maxExec = protos[protos.length - 1]?.avg_settlement_ms || 1}
			<div style="
				background: var(--bg-1);
				border: 1px solid var(--bd);
				border-radius: 6px;
				padding: 24px;
				transition: border-color 0.2s;
			" onmouseenter={(e) => e.currentTarget.style.borderColor = c}
			   onmouseleave={(e) => e.currentTarget.style.borderColor = 'var(--bd)'}>

				<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
					<div style="display:flex; align-items:center; gap:8px;">
						<span style="width:10px; height:10px; border-radius:50%; background:{c};"></span>
						<span style="font-family:var(--mono); font-weight:700; font-size:18px; color:{c};">{p.protocol.toUpperCase()}</span>
						<span style="font-size:11px; color:var(--tx-3); margin-left:4px;">{m?.stack}</span>
					</div>
					<div style="font-family:var(--mono); font-size:12px; color:var(--tx-3);">
						{ms(p.avg_settlement_ms)} exec · {ms(p.avg_authorization_ms)} auth · {m?.fee} fee
					</div>
				</div>

				<p style="font-size:13px; color:var(--tx-2); margin-bottom:16px; line-height:1.5;">{m?.desc}</p>

				<div style="display:grid; grid-template-columns:repeat(5, 1fr); gap:10px; margin-bottom:16px;">
					{#each [
						{ v: p.total_transactions, l: 'Transactions' },
						{ v: fmt(v), l: 'Volume' },
						{ v: fmt(f), l: 'Fees' },
						{ v: v > 0 ? `${((f/v)*100).toFixed(2)}%` : '—', l: 'Fee Rate' },
						{ v: p.micropayment_count, l: 'Micropayments' },
					] as s}
						<div style="background:var(--bg-2); border-radius:4px; padding:12px; text-align:center;">
							<div style="font-family:var(--mono); font-size:18px; font-weight:700;">{s.v}</div>
							<div style="font-size:9px; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em; margin-top:4px;">{s.l}</div>
						</div>
					{/each}
				</div>

				<!-- Execution bar -->
				<div>
					<div style="display:flex; justify-content:space-between; font-size:10px; color:var(--tx-3); margin-bottom:4px;">
						<span>Execution Time</span>
						<span>{ms(p.avg_settlement_ms)}</span>
					</div>
					<div style="height:4px; background:var(--bg-0); border-radius:2px; overflow:hidden;">
						<div style="height:100%; border-radius:2px; background:{c}; width:{Math.min((p.avg_settlement_ms / maxExec) * 100, 100)}%; transition:width 0.5s;"></div>
					</div>
				</div>
			</div>
		{/each}
	</div>
</div>
