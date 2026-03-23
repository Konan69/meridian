<script lang="ts">
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

	interface Props {
		metrics: ProtoMetric[];
	}

	let { metrics }: Props = $props();

	const protocolColors: Record<string, string> = {
		acp: '#3b82f6',
		ap2: '#ef4444',
		x402: '#10b981',
		mpp: '#8b5cf6',
		atxp: '#f59e0b',
	};

	function color(protocol: string): string {
		return protocolColors[protocol.toLowerCase()] ?? '#6b7280';
	}

	function fmtDollars(cents: number): string {
		if (cents >= 100_000) return `$${(cents / 100).toFixed(0)}`;
		return `$${(cents / 100).toFixed(2)}`;
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

	const barHeight = 28;
	const labelWidth = 110;
	const chartPadding = { top: 32, right: 80, bottom: 8, left: 0 };
	let chartWidth = $derived(400);

	function svgHeight(count: number): number {
		return chartPadding.top + count * (barHeight + 8) + chartPadding.bottom;
	}

	/** Log-scale mapping for execution time: compress large values */
	function logScale(value: number, max: number): number {
		if (value <= 0 || max <= 0) return 0;
		return Math.log(value + 1) / Math.log(max + 1);
	}
</script>

<div style="
	display:grid; grid-template-columns:1fr 1fr; gap:12px;
	font-family:var(--sans);
">
	<!-- 1. Volume by Protocol -->
	<div style="background:var(--bg-2); border:1px solid var(--bd); border-radius:6px; padding:16px; overflow:hidden;">
		<svg viewBox="0 0 {chartWidth} {svgHeight(volumeData.length)}" style="width:100%; height:auto;">
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
		<svg viewBox="0 0 {chartWidth} {svgHeight(feeData.length)}" style="width:100%; height:auto;">
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
		<svg viewBox="0 0 {chartWidth} {svgHeight(execData.length)}" style="width:100%; height:auto;">
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
		<svg viewBox="0 0 {chartWidth} {svgHeight(successData.length)}" style="width:100%; height:auto;">
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
</div>
