<script lang="ts">
	import { PROTOCOL_COLORS } from '$lib/constants';
	import { buildNoRoutePressureRows, formatRoutePressureLabel } from '$lib/routePressureDisplay';
	import type { RoutePressureSummary } from '$lib/stores/simulation.svelte';

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
		routePressureSummary?: RoutePressureSummary[];
		floatSummary?: Record<string, number>;
		railPnlHistory?: Record<string, number[]>;
	}

	let {
		metrics,
		ecosystem = {},
		routeUsage = {},
		routePressureSummary = [],
		floatSummary = {},
		railPnlHistory = {},
	}: Props = $props();

	function color(protocol: string): string {
		return PROTOCOL_COLORS[protocol.toLowerCase()] ?? '#6b7280';
	}

	function fmtDollars(cents: number): string {
		const safeCents = numberFrom(cents) ?? 0;
		const sign = safeCents < 0 ? '-' : '';
		const absCents = Math.abs(safeCents);
		if (absCents >= 100_000) return `${sign}$${(absCents / 100).toFixed(0)}`;
		return `${sign}$${(absCents / 100).toFixed(2)}`;
	}

	function signedDollars(cents: number): string {
		const safeCents = numberFrom(cents) ?? 0;
		return `${safeCents >= 0 ? '+' : '-'}${fmtDollars(Math.abs(safeCents))}`;
	}

	function fmtMs(n: number): string {
		const safeMs = nonNegativeNumber(n);
		if (safeMs < 1) return `${(safeMs * 1000).toFixed(0)}us`;
		if (safeMs < 100) return `${safeMs.toFixed(1)}ms`;
		return `${safeMs.toFixed(0)}ms`;
	}

	let metricData = $derived(metrics.map(cleanMetric));

	let railProtocols = $derived(
		Array.from(new Set([
			...metricData.map(m => m.protocol),
			...Object.keys(ecosystem),
			...Object.keys(railPnlHistory),
		])).sort()
	);

	let volumeData = $derived(
		[...metricData].sort((a, b) => b.total_volume_cents - a.total_volume_cents)
	);
	let volumeMax = $derived(Math.max(...volumeData.map(m => m.total_volume_cents), 1));

	let feeData = $derived(
		metricData.map(m => ({
			...m,
			feeRate: m.total_volume_cents > 0 ? (m.total_fees_cents / m.total_volume_cents) * 100 : 0,
		})).sort((a, b) => a.feeRate - b.feeRate)
	);
	let feeMax = $derived(Math.max(...feeData.map(m => m.feeRate), 0.01));

	let execData = $derived(
		[...metricData].sort((a, b) => a.avg_settlement_ms - b.avg_settlement_ms)
	);
	let execMax = $derived(Math.max(...execData.map(m => m.avg_settlement_ms), 1));

	let successData = $derived(
		metricData.map(m => ({
			...m,
			rate: m.total_transactions > 0 ? unit(m.successful_transactions / m.total_transactions) * 100 : 0,
		})).sort((a, b) => b.rate - a.rate)
	);

	let marginData = $derived(
		railProtocols.map(protocol => {
			const history = finiteValues(railPnlHistory[protocol]);
			const finalFromHistory = history.length > 0 ? history[history.length - 1] : undefined;
			const margin_cents = numberFrom(ecosystem[protocol]?.operator_margin_cents, finalFromHistory) ?? 0;
			const first_cents = history.length > 0 ? history[0] : margin_cents;
			return {
				protocol,
				margin_cents,
				delta_cents: margin_cents - first_cents,
				snapshots: history.length || 1,
			};
		}).sort((a, b) => b.margin_cents - a.margin_cents)
	);
	let marginAbsMax = $derived(Math.max(...marginData.map(m => Math.abs(m.margin_cents)), 1));

	let adoptionData = $derived(
		railProtocols.map(protocol => ({
			protocol,
			merchant_count: wholeNonNegative(ecosystem[protocol]?.merchant_count),
			network_effect: unit(numberFrom(ecosystem[protocol]?.network_effect) ?? 0),
			congestion: unit(numberFrom(ecosystem[protocol]?.congestion) ?? 0),
		})).sort((a, b) => b.network_effect - a.network_effect)
	);

	let floatData = $derived(
		Object.entries(floatSummary)
			.map(([domain, amount]) => [domain, nonNegativeNumber(amount)] as [string, number])
			.filter(([, amount]) => amount > 0)
			.sort(([, a], [, b]) => b - a)
	);
	let floatMax = $derived(Math.max(...floatData.map(([, amount]) => amount), 1));

	let routeData = $derived(
		Object.entries(routeUsage)
			.map(([route, usageCents]) => [route, nonNegativeNumber(usageCents)] as [string, number])
			.filter(([, usageCents]) => usageCents > 0)
			.sort(([, a], [, b]) => b - a)
			.slice(0, 8)
	);
	let routeMax = $derived(Math.max(...routeData.map(([, count]) => count), 1));
	let noRoutePressureRows = $derived(buildNoRoutePressureRows(routePressureSummary));
	let visibleNoRoutePressureRows = $derived(noRoutePressureRows.slice(0, 4));

	const barHeight = 26;
	const labelWidth = 118;
	const chartPadding = { top: 30, right: 92, bottom: 8, left: 0 };
	const chartWidth = 440;
	const plotWidth = chartWidth - labelWidth - chartPadding.right;
	const marginAxisX = labelWidth + plotWidth / 2;
	const marginHalfWidth = Math.max(24, plotWidth / 2 - 6);

	function svgHeight(count: number): number {
		return chartPadding.top + Math.max(count, 1) * (barHeight + 8) + chartPadding.bottom;
	}

	/** Log-scale mapping for execution time: compress large values */
	function logScale(value: number, max: number): number {
		if (!Number.isFinite(value) || !Number.isFinite(max) || value <= 0 || max <= 0) return 0;
		return Math.log(value + 1) / Math.log(max + 1);
	}

	function scaledWidth(value: number, max: number, maxWidth = plotWidth): number {
		if (!Number.isFinite(value) || !Number.isFinite(max) || value <= 0 || max <= 0) return 0;
		return Math.max(2, Math.min(maxWidth, (value / max) * maxWidth));
	}

	function unit(value: number): number {
		if (!Number.isFinite(value)) return 0;
		return Math.max(0, Math.min(1, value));
	}

	function compactLabel(value: string, max = 18): string {
		return value.length > max ? `${value.slice(0, max - 3)}...` : value;
	}

	function formatLabel(value: string) {
		return formatRoutePressureLabel(value);
	}

	function cleanMetric(metric: ProtoMetric): ProtoMetric {
		const protocol = typeof metric.protocol === 'string' ? metric.protocol.trim() : '';
		return {
			protocol: protocol || 'unknown',
			total_transactions: wholeNonNegative(metric.total_transactions),
			total_volume_cents: nonNegativeNumber(metric.total_volume_cents),
			total_fees_cents: nonNegativeNumber(metric.total_fees_cents),
			avg_settlement_ms: nonNegativeNumber(metric.avg_settlement_ms),
			micropayment_count: wholeNonNegative(metric.micropayment_count),
			successful_transactions: wholeNonNegative(metric.successful_transactions),
			failed_transactions: wholeNonNegative(metric.failed_transactions),
		};
	}

	function numberFrom(...values: unknown[]) {
		for (const value of values) {
			if (typeof value === 'number' && Number.isFinite(value)) return value;
			if (typeof value === 'string' && value.trim()) {
				const parsed = Number(value);
				if (Number.isFinite(parsed)) return parsed;
			}
		}
		return null;
	}

	function nonNegativeNumber(value: unknown) {
		return Math.max(0, numberFrom(value) ?? 0);
	}

	function wholeNonNegative(value: unknown) {
		return Math.max(0, Math.trunc(numberFrom(value) ?? 0));
	}

	function finiteValues(values: number[] | undefined) {
		return (values ?? []).flatMap((value) => {
			const numeric = numberFrom(value);
			return numeric == null ? [] : [numeric];
		});
	}

</script>

<div class="market-charts-grid">
	<!-- 1. Volume by Protocol -->
	<div class="chart-card">
		<svg viewBox="0 0 {chartWidth} {svgHeight(volumeData.length)}" role="img" aria-label="Volume by protocol bar chart" style="width:100%; height:auto;">
			<title>Volume by Protocol</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Volume by Protocol</text>
			{#each volumeData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = scaledWidth(m.total_volume_cents, volumeMax)}
				<!-- Protocol dot + label -->
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<!-- Bar -->
				<rect x={labelWidth} y={y} width={barW} height={barHeight} rx="3" fill={color(m.protocol)} opacity="0.85" />
				<!-- Value -->
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{fmtDollars(m.total_volume_cents)}
				</text>
			{:else}
				<text x="0" y={chartPadding.top + 16} fill="var(--tx-3)" font-size="11" font-family="var(--mono)">No finite protocol volume yet</text>
			{/each}
		</svg>
	</div>

	<!-- 2. Fee Rate Comparison -->
	<div class="chart-card">
		<svg viewBox="0 0 {chartWidth} {svgHeight(feeData.length)}" role="img" aria-label="Fee rate comparison bar chart" style="width:100%; height:auto;">
			<title>Fee Rate Comparison</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Fee Rate Comparison</text>
			{#each feeData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = scaledWidth(m.feeRate, feeMax)}
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<rect x={labelWidth} y={y} width={barW} height={barHeight} rx="3" fill={color(m.protocol)} opacity="0.85" />
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{m.feeRate.toFixed(2)}%
				</text>
			{:else}
				<text x="0" y={chartPadding.top + 16} fill="var(--tx-3)" font-size="11" font-family="var(--mono)">No finite fee data yet</text>
			{/each}
		</svg>
	</div>

	<!-- 3. Execution Time (log scale) -->
	<div class="chart-card">
		<svg viewBox="0 0 {chartWidth} {svgHeight(execData.length)}" role="img" aria-label="Execution time by protocol bar chart" style="width:100%; height:auto;">
			<title>Execution Time</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Execution Time</text>
			{#each execData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = scaledWidth(logScale(m.avg_settlement_ms, execMax), 1)}
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<rect x={labelWidth} y={y} width={barW} height={barHeight} rx="3" fill={color(m.protocol)} opacity="0.85" />
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{fmtMs(m.avg_settlement_ms)}
				</text>
			{:else}
				<text x="0" y={chartPadding.top + 16} fill="var(--tx-3)" font-size="11" font-family="var(--mono)">No finite execution data yet</text>
			{/each}
		</svg>
	</div>

	<!-- 4. Success Rate -->
	<div class="chart-card">
		<svg viewBox="0 0 {chartWidth} {svgHeight(successData.length)}" role="img" aria-label="Success rate by protocol bar chart" style="width:100%; height:auto;">
			<title>Success Rate</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Success Rate</text>
			{#each successData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = scaledWidth(m.rate, 100)}
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<!-- Background track -->
				<rect x={labelWidth} y={y} width={plotWidth} height={barHeight} rx="3" fill="var(--bg-0)" opacity="0.5" />
				<!-- Fill -->
				<rect x={labelWidth} y={y} width={barW} height={barHeight} rx="3" fill={color(m.protocol)} opacity="0.85" />
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{m.rate.toFixed(1)}%
				</text>
			{:else}
				<text x="0" y={chartPadding.top + 16} fill="var(--tx-3)" font-size="11" font-family="var(--mono)">No transaction success data yet</text>
			{/each}
		</svg>
	</div>

	<!-- 5. Rail P&L -->
	<div class="chart-card">
		<svg viewBox="0 0 {chartWidth} {svgHeight(marginData.length)}" role="img" aria-label="Rail PnL final margin and drift chart" style="width:100%; height:auto;">
			<title>Rail PnL Final Margin</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Rail P&amp;L Final Margin</text>
			{#each marginData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const width = scaledWidth(Math.abs(m.margin_cents), marginAbsMax, marginHalfWidth)}
				{@const positive = m.margin_cents >= 0}
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<line x1={marginAxisX} y1={y - 2} x2={marginAxisX} y2={y + barHeight + 2} stroke="var(--bd)" stroke-width="1" />
				<rect
					x={positive ? marginAxisX : marginAxisX - width}
					y={y}
					width={width}
					height={barHeight}
					rx="3"
					fill={positive ? 'var(--x402)' : 'var(--ap2)'}
					opacity="0.85"
				/>
				<text x={labelWidth + plotWidth + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{fmtDollars(m.margin_cents)} ({signedDollars(m.delta_cents)}, {m.snapshots}r)
				</text>
			{:else}
				<text x="0" y={chartPadding.top + 16} fill="var(--tx-3)" font-size="11" font-family="var(--mono)">No rail margin snapshots yet</text>
			{/each}
		</svg>
	</div>

	<!-- 6. Adoption / Pressure -->
	<div class="chart-card">
		<svg viewBox="0 0 {chartWidth} {svgHeight(adoptionData.length)}" role="img" aria-label="Rail adoption and pressure chart" style="width:100%; height:auto;">
			<title>Adoption &amp; Pressure</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Adoption &amp; Pressure</text>
			{#each adoptionData as m, i}
				{@const y = chartPadding.top + i * (barHeight + 12)}
				{@const adoptionW = scaledWidth(unit(m.network_effect), 1)}
				{@const congestionW = scaledWidth(unit(m.congestion), 1)}
				<circle cx="8" cy={y + barHeight / 2} r="4" fill={color(m.protocol)} />
				<text x="18" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="var(--sans)">
					{m.protocol.toUpperCase()}
				</text>
				<rect x={labelWidth} y={y} width={plotWidth} height={10} rx="3" fill="var(--bg-0)" opacity="0.5" />
				<rect x={labelWidth} y={y} width={adoptionW} height={10} rx="3" fill={color(m.protocol)} opacity="0.85" />
				<rect x={labelWidth} y={y + 16} width={congestionW} height={8} rx="3" fill="var(--ap2)" opacity="0.75" />
				<text x={labelWidth + adoptionW + 6} y={y + 9} fill="var(--tx-2)" font-size="10" font-family="'Berkeley Mono', var(--mono), monospace">
					NE {m.network_effect.toFixed(2)}
				</text>
				<text x={labelWidth + congestionW + 6} y={y + 23} fill="var(--tx-3)" font-size="10" font-family="'Berkeley Mono', var(--mono), monospace">
					CG {m.congestion.toFixed(2)} · {m.merchant_count} merchants
				</text>
			{:else}
				<text x="0" y={chartPadding.top + 16} fill="var(--tx-3)" font-size="11" font-family="var(--mono)">No ecosystem adoption data yet</text>
			{/each}
		</svg>
	</div>

	<!-- 7. Stablecoin Float -->
	<div class="chart-card">
		<svg viewBox="0 0 {chartWidth} {svgHeight(floatData.length)}" role="img" aria-label="Stablecoin float by domain chart" style="width:100%; height:auto;">
			<title>Stablecoin Float</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Stablecoin Float</text>
			{#each floatData as [domain, amount], i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = scaledWidth(amount, floatMax)}
				<text x="0" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="10" font-family="var(--mono)">{compactLabel(domain)}</text>
				<rect x={labelWidth} y={y} width={barW} height={barHeight} rx="3" fill="var(--x402)" opacity="0.85" />
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{fmtDollars(amount)}
				</text>
			{:else}
				<text x="0" y={chartPadding.top + 16} fill="var(--tx-3)" font-size="11" font-family="var(--mono)">No positive stablecoin float yet</text>
			{/each}
		</svg>
	</div>

	<!-- 8. Route Usage -->
	<div class="chart-card">
		<svg viewBox="0 0 {chartWidth} {svgHeight(routeData.length)}" role="img" aria-label="Route reserved principal chart" style="width:100%; height:auto;">
			<title>Route Usage Reserved Principal</title>
			<text x="0" y="16" fill="var(--tx-2)" font-size="12" font-weight="600" font-family="var(--sans)">Route Usage · Reserved Principal</text>
			{#each routeData as [route, usageCents], i}
				{@const y = chartPadding.top + i * (barHeight + 8)}
				{@const barW = scaledWidth(usageCents, routeMax)}
				<text x="0" y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="10" font-family="var(--mono)">{compactLabel(route)}</text>
				<rect x={labelWidth} y={y} width={barW} height={barHeight} rx="3" fill="var(--mpp)" opacity="0.85" />
				<text x={labelWidth + barW + 6} y={y + barHeight / 2 + 4} fill="var(--tx-2)" font-size="11" font-family="'Berkeley Mono', var(--mono), monospace">
					{fmtDollars(usageCents)}
				</text>
			{:else}
				<text x="0" y={chartPadding.top + 16} fill="var(--tx-3)" font-size="11" font-family="var(--mono)">No positive route principal yet</text>
			{/each}
		</svg>
		{#if visibleNoRoutePressureRows.length > 0}
			<div class="route-pressure-chips" aria-label="No-route treasury pressure">
				<div class="chip-heading">
					<span>No-route treasury pressure</span>
					<strong>{noRoutePressureRows.length}</strong>
				</div>
				{#each visibleNoRoutePressureRows as row}
					<div class="pressure-chip-row">
						<div class="pressure-main">
							<span class="pressure-route">{compactLabel(row.route, 24)}</span>
							<strong>{(row.capacityRatio * 100).toFixed(0)}%</strong>
						</div>
						<div class="pressure-meta">
							<span>{compactLabel(row.domains, 28)}</span>
							<span>{row.pressureRounds}r</span>
							{#if row.failureCount != null}
								<span>{row.failureCount} fail</span>
							{/if}
							{#if row.merchant}
								<span>{compactLabel(row.merchant, 20)}</span>
							{/if}
						</div>
						<div class="pressure-tags">
							<span class="pressure-tag pressure-critical">{formatLabel('no_feasible_rebalance_route')}</span>
							{#each row.protocols.slice(0, 3) as protocol}
								<span class="pressure-tag" style={`border-color:${color(protocol)}; color:${color(protocol)}`}>
									{protocol.toUpperCase()}
								</span>
							{/each}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.market-charts-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr));
		gap: 12px;
		font-family: var(--sans);
	}

	.chart-card {
		min-width: 0;
		overflow: hidden;
		border: 1px solid var(--bd);
		border-radius: 6px;
		background: var(--bg-2);
		padding: 14px;
	}

	.route-pressure-chips {
		display: grid;
		gap: 8px;
		margin-top: 10px;
		padding-top: 10px;
		border-top: 1px solid var(--bd);
	}

	.chip-heading,
	.pressure-main,
	.pressure-meta,
	.pressure-tags {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}

	.chip-heading,
	.pressure-main {
		justify-content: space-between;
	}

	.chip-heading {
		color: var(--tx-3);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0;
		text-transform: uppercase;
	}

	.chip-heading strong,
	.pressure-main strong {
		font-family: var(--mono);
	}

	.pressure-chip-row {
		min-width: 0;
		border: 1px solid color-mix(in srgb, var(--ap2) 28%, var(--bd));
		border-radius: 4px;
		background: color-mix(in srgb, var(--ap2) 8%, var(--bg-2));
		padding: 8px;
	}

	.pressure-main {
		color: var(--tx-1);
		font-family: var(--mono);
		font-size: 11px;
	}

	.pressure-route,
	.pressure-meta span {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.pressure-meta {
		flex-wrap: wrap;
		margin-top: 5px;
		color: var(--tx-3);
		font-family: var(--mono);
		font-size: 10px;
	}

	.pressure-tags {
		flex-wrap: wrap;
		margin-top: 7px;
	}

	.pressure-tag {
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		border: 1px solid var(--bd);
		border-radius: 999px;
		padding: 3px 7px;
		color: var(--tx-2);
		font-family: var(--mono);
		font-size: 10px;
	}

	.pressure-critical {
		border-color: color-mix(in srgb, var(--ap2) 55%, var(--bd));
		background: color-mix(in srgb, var(--ap2) 12%, transparent);
		color: var(--ap2);
	}
</style>
