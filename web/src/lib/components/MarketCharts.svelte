<script lang="ts">
	import { PROTOCOL_COLORS } from '$lib/constants';

	interface ProtoMetric {
		protocol: string;
		total_transactions: number;
		total_volume_cents: number;
		total_fees_cents: number;
		avg_settlement_ms: number;
		micropayment_count: number;
		successful_transactions: number;
		failed_transactions: number;
	}

	interface ProtocolEcosystem {
		merchant_count: number;
		network_effect: number;
		congestion: number;
		operator_margin_cents: number;
		reliability?: number;
		route_mix?: Record<string, number>;
	}

	interface Props {
		metrics: ProtoMetric[];
		ecosystem?: Record<string, ProtocolEcosystem>;
		routeUsage?: Record<string, number>;
		floatSummary?: Record<string, number>;
		railPnlHistory?: Record<string, number[]>;
	}

	let { metrics, ecosystem = {}, routeUsage = {}, floatSummary = {}, railPnlHistory = {} }: Props = $props();

	function color(protocol: string): string {
		return PROTOCOL_COLORS[protocol.toLowerCase()] ?? '#6b7280';
	}

	function fmtDollars(cents: number): string {
		if (cents >= 100_000) return `$${(cents / 100).toFixed(0)}`;
		return `$${(cents / 100).toFixed(2)}`;
	}

	function signedDollars(cents: number): string {
		return `${cents >= 0 ? '+' : '-'}${fmtDollars(Math.abs(cents))}`;
	}

	function fmtMs(n: number): string {
		if (n < 1) return `${(n * 1000).toFixed(0)}us`;
		if (n < 100) return `${n.toFixed(1)}ms`;
		return `${n.toFixed(0)}ms`;
	}

	// Chart data derivations
	let volumeData = $derived(
		[...metrics].sort((a, b) => b.total_volume_cents - a.total_volume_cents)
	);
	let volumeMax = $derived(Math.max(...metrics.map(m => m.total_volume_cents), 1));

	let feeData = $derived(
		metrics.map(m => ({
			...m,
			feeRate: m.total_volume_cents > 0 ? (m.total_fees_cents / m.total_volume_cents) * 100 : 0,
		})).sort((a, b) => a.feeRate - b.feeRate)
	);
	let feeMax = $derived(Math.max(...feeData.map(m => m.feeRate), 0.01));

	let execData = $derived(
		[...metrics].sort((a, b) => a.avg_settlement_ms - b.avg_settlement_ms)
	);
	let execMax = $derived(Math.max(...metrics.map(m => m.avg_settlement_ms), 1));

	let successData = $derived(
		metrics.map(m => ({
			...m,
			rate: m.total_transactions > 0 ? (m.successful_transactions / m.total_transactions) * 100 : 0,
		})).sort((a, b) => b.rate - a.rate)
	);

	let marginData = $derived(
		metrics.map(m => {
			const history = railPnlHistory[m.protocol] ?? [];
			const finalFromHistory = history.length > 0 ? history[history.length - 1] : undefined;
			const margin_cents = ecosystem[m.protocol]?.operator_margin_cents ?? finalFromHistory ?? 0;
			const first_cents = history.length > 0 ? history[0] : margin_cents;
			return {
				protocol: m.protocol,
				margin_cents,
				delta_cents: margin_cents - first_cents,
				snapshots: history.length || 1,
			};
		}).sort((a, b) => b.margin_cents - a.margin_cents)
	);
	let marginAbsMax = $derived(Math.max(...marginData.map(m => Math.abs(m.margin_cents)), 1));

	let adoptionData = $derived(
		metrics.map(m => ({
			protocol: m.protocol,
			merchant_count: ecosystem[m.protocol]?.merchant_count ?? 0,
			network_effect: ecosystem[m.protocol]?.network_effect ?? 0,
			congestion: ecosystem[m.protocol]?.congestion ?? 0,
		})).sort((a, b) => b.network_effect - a.network_effect)
	);

	let floatData = $derived(
		Object.entries(floatSummary).sort(([, a], [, b]) => b - a)
	);
	let floatMax = $derived(Math.max(...floatData.map(([, amount]) => amount), 1));

	let routeData = $derived(
		Object.entries(routeUsage).sort(([, a], [, b]) => b - a).slice(0, 8)
	);
	let routeMax = $derived(Math.max(...routeData.map(([, count]) => count), 1));

	const barHeight = 28;
	const labelWidth = 110;
	const chartPadding = { top: 32, right: 80, bottom: 8, left: 0 };
	let chartWidth = $derived(400);

	// Responsive chart width
	$effect(() => {
		const updateWidth = () => {
			const container = document.querySelector('.market-charts-grid');
			if (container) {
				chartWidth = Math.max(200, container.clientWidth - 64);
			}
		};
		updateWidth();
		window.addEventListener('resize', updateWidth);
		return () => window.removeEventListener('resize', updateWidth);
	});

	function svgHeight(count: number): number {
		return chartPadding.top + count * (barHeight + 8) + chartPadding.bottom;
	}

	/** Log-scale mapping for execution time: compress large values */
	function logScale(value: number, max: number): number {
		if (value <= 0 || max <= 0) return 0;
		return Math.log(value + 1) / Math.log(max + 1);
	}
</script>

<div class="market-charts-grid" style="
	display:grid; grid-template-columns:1fr 1fr; gap:12px;
	font-family:var(--sans);
">
	<!-- 1. Volume by Protocol -->
	<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:16px; overflow:hidden;">
		<svg viewBox="0 0 {chartWidth} {svgHeight(volumeData.length)}" role="img" aria-label="Volume by protocol bar chart" style="width:100%; height:auto;">
			<title>Volume by Protocol</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Volume by Protocol</text>
			{#each volumeData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = volumeMax > 0 ? (m.total_volume_cents / volumeMax) * (chartWidth - labelWidth - chartPadding.right) : 0}
				<!-- Protocol dot + label -->
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<!-- Bar -->
				<rect x={labelWidth} y={y} width={Math.max(barW, 2)} height={barHeight} rx="3" fill={color(m.protocol)} opacity="0.85" />
				<!-- Value -->
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{fmtDollars(m.total_volume_cents)}
				</text>
			{/each}
		</svg>
	</div>

	<!-- 2. Fee Rate Comparison -->
	<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:16px; overflow:hidden;">
		<svg viewBox="0 0 {chartWidth} {svgHeight(feeData.length)}" role="img" aria-label="Fee rate comparison bar chart" style="width:100%; height:auto;">
			<title>Fee Rate Comparison</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Fee Rate Comparison</text>
			{#each feeData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = feeMax > 0 ? (m.feeRate / feeMax) * (chartWidth - labelWidth - chartPadding.right) : 0}
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<rect x={labelWidth} y={y} width={Math.max(barW, 2)} height={barHeight} rx="3" fill={color(m.protocol)} opacity="0.85" />
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{m.feeRate.toFixed(2)}%
				</text>
			{/each}
		</svg>
	</div>

	<!-- 3. Execution Time (log scale) -->
	<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:16px; overflow:hidden;">
		<svg viewBox="0 0 {chartWidth} {svgHeight(execData.length)}" role="img" aria-label="Execution time by protocol bar chart" style="width:100%; height:auto;">
			<title>Execution Time</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Execution Time</text>
			{#each execData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = logScale(m.avg_settlement_ms, execMax) * (chartWidth - labelWidth - chartPadding.right)}
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<rect x={labelWidth} y={y} width={Math.max(barW, 2)} height={barHeight} rx="3" fill={color(m.protocol)} opacity="0.85" />
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{fmtMs(m.avg_settlement_ms)}
				</text>
			{/each}
		</svg>
	</div>

	<!-- 4. Success Rate -->
	<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:16px; overflow:hidden;">
		<svg viewBox="0 0 {chartWidth} {svgHeight(successData.length)}" role="img" aria-label="Success rate by protocol bar chart" style="width:100%; height:auto;">
			<title>Success Rate</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Success Rate</text>
			{#each successData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = (m.rate / 100) * (chartWidth - labelWidth - chartPadding.right)}
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<!-- Background track -->
				<rect x={labelWidth} y={y} width={chartWidth - labelWidth - chartPadding.right} height={barHeight} rx="3" fill="var(--bg-0)" opacity="0.5" />
				<!-- Fill -->
				<rect x={labelWidth} y={y} width={Math.max(barW, 2)} height={barHeight} rx="3" fill={color(m.protocol)} opacity="0.85" />
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{m.rate.toFixed(1)}%
				</text>
			{/each}
		</svg>
	</div>

	<!-- 5. Rail P&L -->
	<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:16px; overflow:hidden;">
		<svg viewBox="0 0 {chartWidth} {svgHeight(marginData.length)}" role="img" aria-label="Rail PnL final margin and drift chart" style="width:100%; height:auto;">
			<title>Rail PnL Final Margin</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Rail P&amp;L Final Margin</text>
			{#each marginData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const width = (Math.abs(m.margin_cents) / marginAbsMax) * ((chartWidth - labelWidth - chartPadding.right) * 0.9)}
				{@const positive = m.margin_cents >= 0}
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<line x1={labelWidth + 90} y1={y - 2} x2={labelWidth + 90} y2={y + barHeight + 2} stroke="var(--bd)" stroke-width="1" />
				<rect
					x={positive ? labelWidth + 90 : labelWidth + 90 - width}
					y={y}
					width={Math.max(width, 2)}
					height={barHeight}
					rx="3"
					fill={positive ? 'var(--x402)' : 'var(--ap2)'}
					opacity="0.85"
				/>
				<text x={labelWidth + 100 + (positive ? width : 0)} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{fmtDollars(m.margin_cents)} ({signedDollars(m.delta_cents)}, {m.snapshots}r)
				</text>
			{/each}
		</svg>
	</div>

	<!-- 6. Adoption / Pressure -->
	<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:16px; overflow:hidden;">
		<svg viewBox="0 0 {chartWidth} {svgHeight(adoptionData.length)}" role="img" aria-label="Rail adoption and pressure chart" style="width:100%; height:auto;">
			<title>Adoption &amp; Pressure</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Adoption &amp; Pressure</text>
			{#each adoptionData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 12)}
				{@const adoptionW = m.network_effect * (chartWidth - labelWidth - chartPadding.right)}
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<rect x={labelWidth} y={y} width={chartWidth - labelWidth - chartPadding.right} height={10} rx="3" fill="var(--bg-0)" opacity="0.5" />
				<rect x={labelWidth} y={y} width={Math.max(adoptionW, 2)} height={10} rx="3" fill={color(m.protocol)} opacity="0.85" />
				<rect x={labelWidth} y={y + 16} width={(chartWidth - labelWidth - chartPadding.right) * Math.min(m.congestion, 1)} height={8} rx="3" fill="var(--ap2)" opacity="0.75" />
				<text x={labelWidth + adoptionW + 6} y={y + 9} fill="var(--tx-2)" font-size="10" font-family="'Berkeley Mono', var(--mono), monospace">
					NE {m.network_effect.toFixed(2)}
				</text>
				<text x={labelWidth + (chartWidth - labelWidth - chartPadding.right) * Math.min(m.congestion, 1) + 6} y={y + 23} fill="var(--tx-3)" font-size="10" font-family="'Berkeley Mono', var(--mono), monospace">
					CG {m.congestion.toFixed(2)} · {m.merchant_count} merchants
				</text>
			{/each}
		</svg>
	</div>

	<!-- 7. Stablecoin Float -->
	<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:16px; overflow:hidden;">
		<svg viewBox="0 0 {chartWidth} {svgHeight(floatData.length)}" role="img" aria-label="Stablecoin float by domain chart" style="width:100%; height:auto;">
			<title>Stablecoin Float</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Stablecoin Float</text>
			{#each floatData as [domain, amount], i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = floatMax > 0 ? (amount / floatMax) * (chartWidth - labelWidth - chartPadding.right) : 0}
				<text x="0" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="10" font-family="var(--mono)">{domain}</text>
				<rect x={labelWidth} y={y} width={Math.max(barW, 2)} height={barHeight} rx="3" fill="var(--x402)" opacity="0.85" />
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{fmtDollars(amount)}
				</text>
			{/each}
		</svg>
	</div>

	<!-- 8. Route Usage -->
	<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:16px; overflow:hidden;">
		<svg viewBox="0 0 {chartWidth} {svgHeight(routeData.length)}" role="img" aria-label="Route reserved principal chart" style="width:100%; height:auto;">
			<title>Route Usage Reserved Principal</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Route Usage · Reserved Principal</text>
			{#each routeData as [route, usageCents], i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = routeMax > 0 ? (usageCents / routeMax) * (chartWidth - labelWidth - chartPadding.right) : 0}
				<text x="0" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="10" font-family="var(--mono)">{route}</text>
				<rect x={labelWidth} y={y} width={Math.max(barW, 2)} height={barHeight} rx="3" fill="var(--mpp)" opacity="0.85" />
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{fmtDollars(usageCents)}
				</text>
			{/each}
		</svg>
	</div>
</div>

<style>
	.market-charts-grid {
		grid-template-columns: 1fr 1fr;
	}
	@media (max-width: 900px) {
		.market-charts-grid { grid-template-columns: 1fr; }
	}
</style>
