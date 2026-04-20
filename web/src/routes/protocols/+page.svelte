<script lang="ts">
	import { onMount } from 'svelte';

	interface PM {
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

	type CapabilityStatus = {
		protocol: string;
		runtime_ready: boolean;
		integration: string;
		reason: string;
	};

	const ENGINE = 'http://localhost:4080';
	const ORDER = ['x402', 'mpp', 'ap2', 'atxp', 'acp'];
	const META: Record<string, { color: string; desc: string; stack: string; fee: string; primitives: string; domains: string; workloads: string }> = {
		acp: {
			color: 'var(--acp)',
			desc: 'Checkout orchestration rail. Stablecoin value is routed into a Stripe-internal settlement sink for structured commerce.',
			stack: 'OpenAI + Stripe',
			fee: '2.9% + 30¢',
			primitives: 'stripe_internal_checkout',
			domains: 'stripe_internal_usd',
			workloads: 'consumer checkout',
		},
		ap2: {
			color: 'var(--ap2)',
			desc: 'Delegated authorization rail. Best when agent trust and cross-domain flexibility matter more than raw speed.',
			stack: 'Google',
			fee: '2.5% + 20¢',
			primitives: 'direct_same_domain, cctp_transfer, lifi_routed',
			domains: 'base_usdc, solana_usdc, gateway_unified_usdc',
			workloads: 'consumer checkout, treasury rebalance',
		},
		x402: {
			color: 'var(--x402)',
			desc: 'Direct stablecoin machine-payment rail. Strongest for same-domain USDC and batched nanopayment execution.',
			stack: 'Coinbase',
			fee: '0.1%',
			primitives: 'direct_same_domain, batched_nanopayment',
			domains: 'base_usdc, solana_usdc, gateway_unified_usdc',
			workloads: 'api micro, consumer checkout',
		},
		mpp: {
			color: 'var(--mpp)',
			desc: 'Session-based machine rail. Works either as Tempo-native streaming spend or a Stripe-internal checkout sink.',
			stack: 'Stripe + Tempo',
			fee: '1.5% + 5¢',
			primitives: 'tempo_session, stripe_internal_checkout',
			domains: 'tempo_usd, stripe_internal_usd',
			workloads: 'api micro, consumer checkout',
		},
		atxp: {
			color: 'var(--atxp)',
			desc: 'Wallet and mandate rail. Useful for agent-to-agent movement and treasury-style stablecoin routing.',
			stack: 'Circuit & Chisel',
			fee: '0.5%',
			primitives: 'direct_same_domain, lifi_routed',
			domains: 'base_usdc, solana_usdc, gateway_unified_usdc',
			workloads: 'api micro, treasury rebalance',
		},
	};

	let metrics = $state<Record<string, PM>>({});
	let statuses = $state<CapabilityStatus[]>([]);

	function fmt(n: number) { return `$${(n / 100).toFixed(2)}`; }
	function ms(n: number) { return n < 1 ? `${(n * 1000).toFixed(0)}μs` : n < 100 ? `${n.toFixed(2)}ms` : `${n.toFixed(0)}ms`; }

	async function refresh() {
		try {
			const [metricsRes, capabilitiesRes] = await Promise.all([
				fetch(`${ENGINE}/metrics`),
				fetch(`${ENGINE}/capabilities`),
			]);
			const metricsBody = await metricsRes.json();
			metrics = Object.fromEntries(
				((metricsBody.protocols as PM[]) ?? []).map((entry) => [entry.protocol, entry]),
			);

			const capabilitiesBody = await capabilitiesRes.json();
			const capabilityStatuses = Array.isArray(capabilitiesBody.protocol_statuses)
				? capabilitiesBody.protocol_statuses as CapabilityStatus[]
				: [];
			statuses = capabilityStatuses.sort(
				(a, b) => ORDER.indexOf(a.protocol) - ORDER.indexOf(b.protocol),
			);
		} catch {
			metrics = {};
			statuses = [];
		}
	}

	onMount(() => {
		refresh();
		const interval = setInterval(refresh, 3000);
		return () => clearInterval(interval);
	});
</script>

<div>
	<h1 style="font-size:22px; font-weight:600; letter-spacing:-0.03em; margin-bottom:24px;">Protocol Deep Dive</h1>

	<div style="display:flex; flex-direction:column; gap:14px;">
		{#each statuses as status}
			{@const m = META[status.protocol]}
			{@const c = m?.color ?? '#888'}
			{@const p = metrics[status.protocol] ?? {
				protocol: status.protocol,
				total_transactions: 0,
				successful_transactions: 0,
				failed_transactions: 0,
				total_volume_cents: 0,
				total_fees_cents: 0,
				avg_settlement_ms: 0,
				avg_authorization_ms: 0,
				micropayment_count: 0,
			}}
			{@const v = p.total_volume_cents}
			{@const f = p.total_fees_cents}
			{@const maxExec = Math.max(...Object.values(metrics).map((entry) => entry.avg_settlement_ms), 1)}
			<div role="article"
				style="
				background: var(--bg-1);
				border: 1px solid {status.runtime_ready ? c : 'var(--bd)'};
				border-radius: 6px;
				padding: 24px;
				opacity: {status.runtime_ready ? 1 : 0.72};
			">

				<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; gap:12px; flex-wrap:wrap;">
					<div style="display:flex; align-items:center; gap:8px;">
						<span style="width:10px; height:10px; border-radius:50%; background:{c};"></span>
						<span style="font-family:var(--mono); font-weight:700; font-size:18px; color:{c};">{status.protocol.toUpperCase()}</span>
						<span style="font-size:11px; color:var(--tx-3); margin-left:4px;">{m?.stack}</span>
						<span style="
							font-family:var(--mono); font-size:10px; padding:3px 6px; border-radius:3px;
							background:{status.runtime_ready ? 'color-mix(in srgb, var(--x402) 18%, transparent)' : 'var(--bg-2)'};
							color:{status.runtime_ready ? 'var(--x402)' : 'var(--tx-3)'};
						">{status.runtime_ready ? 'LIVE' : 'NOT LIVE'}</span>
					</div>
					<div style="font-family:var(--mono); font-size:12px; color:var(--tx-3);">
						{ms(p.avg_settlement_ms)} exec · {ms(p.avg_authorization_ms)} auth · {m?.fee} fee
					</div>
				</div>

				<p style="font-size:13px; color:var(--tx-2); margin-bottom:12px; line-height:1.5;">{m?.desc}</p>
				<p style="font-size:12px; color:var(--tx-3); margin-bottom:16px; line-height:1.5;">
					{status.integration} · {status.reason}
				</p>

				<div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:10px; margin-bottom:16px; font-size:11px;">
					<div style="background:var(--bg-2); border-radius:4px; padding:10px;">
						<div style="font-size:9px; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em; margin-bottom:4px;">Primitives</div>
						<div style="font-family:var(--mono); color:var(--tx-2);">{m?.primitives}</div>
					</div>
					<div style="background:var(--bg-2); border-radius:4px; padding:10px;">
						<div style="font-size:9px; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em; margin-bottom:4px;">Domains</div>
						<div style="font-family:var(--mono); color:var(--tx-2);">{m?.domains}</div>
					</div>
					<div style="background:var(--bg-2); border-radius:4px; padding:10px;">
						<div style="font-size:9px; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em; margin-bottom:4px;">Best Workloads</div>
						<div style="font-family:var(--mono); color:var(--tx-2);">{m?.workloads}</div>
					</div>
				</div>

				<div style="display:grid; grid-template-columns:repeat(5, 1fr); gap:10px; margin-bottom:16px;">
					{#each [
						{ v: p.total_transactions, l: 'Transactions' },
						{ v: fmt(v), l: 'Volume' },
						{ v: fmt(f), l: 'Fees' },
						{ v: v > 0 ? `${((f / v) * 100).toFixed(2)}%` : '—', l: 'Fee Rate' },
						{ v: p.micropayment_count, l: 'Micropayments' },
					] as stat}
						<div style="background:var(--bg-2); border-radius:4px; padding:12px; text-align:center;">
							<div style="font-family:var(--mono); font-size:18px; font-weight:700;">{stat.v}</div>
							<div style="font-size:9px; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em; margin-top:4px;">{stat.l}</div>
						</div>
					{/each}
				</div>

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
