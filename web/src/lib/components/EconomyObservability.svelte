<script lang="ts">
	import { PROTOCOL_COLORS } from '$lib/constants';
	import type {
		EconomyWorldEvent,
		ProtoMetrics,
		ProtocolEcosystem,
		SimEvent,
	} from '$lib/stores/simulation.svelte';

	type Evidence = Record<string, unknown>;

	interface MerchantSwitchRow {
		merchantId: string;
		merchant: string;
		action: string;
		protocol: string;
		round: number;
		reason: string;
		evidence: Evidence;
	}

	interface RouteMixPart {
		protocol: string;
		count: number;
	}

	interface RouteRow {
		route: string;
		usageCents: number;
		attempts: number;
		protocols: RouteMixPart[];
	}

	interface RailRow {
		protocol: string;
		marginCents: number;
		deltaCents: number;
		snapshots: number;
		routeAttempts: number;
		reliability: number | null;
	}

	interface Props {
		metrics: ProtoMetrics[];
		ecosystem?: Record<string, ProtocolEcosystem>;
		routeUsage?: Record<string, number>;
		railPnlHistory?: Record<string, number[]>;
		worldEvents?: EconomyWorldEvent[];
		events?: SimEvent[];
	}

	let {
		metrics,
		ecosystem = {},
		routeUsage = {},
		railPnlHistory = {},
		worldEvents = [],
		events = [],
	}: Props = $props();

	const evidenceOrder = [
		'adoption_score',
		'removal_risk',
		'avg_trust',
		'recent_memory_signal',
		'route_pressure',
		'treasury_pressure',
		'serves_preferred_domain',
		'reliability',
		'operator_margin_cents',
	];

	let routeRows = $derived(buildRouteRows(routeUsage, ecosystem));
	let routeTotalCents = $derived(routeRows.reduce((sum, row) => sum + row.usageCents, 0));
	let routeMaxCents = $derived(Math.max(...routeRows.map((row) => row.usageCents), 1));
	let railRows = $derived(buildRailRows(metrics, ecosystem, railPnlHistory));
	let railMaxAbs = $derived(Math.max(...railRows.map((row) => Math.abs(row.marginCents)), 1));
	let switchRows = $derived(collectMerchantSwitches(events, worldEvents));

	function buildRouteRows(
		usage: Record<string, number>,
		state: Record<string, ProtocolEcosystem>,
	): RouteRow[] {
		const mix = new Map<string, Map<string, number>>();
		for (const [protocol, ecosystemState] of Object.entries(state)) {
			for (const [route, count] of Object.entries(ecosystemState.route_mix ?? {})) {
				const protocolMix = mix.get(route) ?? new Map<string, number>();
				protocolMix.set(protocol, (protocolMix.get(protocol) ?? 0) + count);
				mix.set(route, protocolMix);
			}
		}

		return Object.entries(usage)
			.map(([route, usageCents]) => {
				const protocolMap = mix.get(route) ?? new Map<string, number>();
				const protocols = Array.from(protocolMap.entries())
					.map(([protocol, count]) => ({ protocol, count }))
					.sort((a, b) => b.count - a.count || a.protocol.localeCompare(b.protocol));
				return {
					route,
					usageCents,
					attempts: protocols.reduce((sum, part) => sum + part.count, 0),
					protocols,
				};
			})
			.sort((a, b) => b.usageCents - a.usageCents || b.attempts - a.attempts);
	}

	function buildRailRows(
		protocolMetrics: ProtoMetrics[],
		state: Record<string, ProtocolEcosystem>,
		historyByProtocol: Record<string, number[]>,
	): RailRow[] {
		const protocols = new Set<string>([
			...protocolMetrics.map((metric) => metric.protocol),
			...Object.keys(state),
			...Object.keys(historyByProtocol),
		]);

		return Array.from(protocols)
			.map((protocol) => {
				const history = historyByProtocol[protocol] ?? [];
				const ecosystemState = state[protocol];
				const lastHistoryValue = history.length > 0 ? history[history.length - 1] : undefined;
				const marginCents = ecosystemState?.operator_margin_cents ?? lastHistoryValue ?? 0;
				const firstHistoryValue = history.length > 0 ? history[0] : marginCents;
				const routeAttempts = Object.values(ecosystemState?.route_mix ?? {})
					.reduce((sum, count) => sum + count, 0);
				return {
					protocol,
					marginCents,
					deltaCents: marginCents - firstHistoryValue,
					snapshots: history.length,
					routeAttempts,
					reliability: ecosystemState?.reliability ?? null,
				};
			})
			.sort((a, b) => Math.abs(b.marginCents) - Math.abs(a.marginCents) || a.protocol.localeCompare(b.protocol));
	}

	function collectMerchantSwitches(
		streamEvents: SimEvent[],
		completedWorldEvents: EconomyWorldEvent[],
	): MerchantSwitchRow[] {
		const rows = new Map<string, MerchantSwitchRow>();
		for (const event of streamEvents) {
			if (event.type === 'merchant_switch') addSwitch(rows, switchFromRecord(event));
		}
		for (const event of completedWorldEvents) {
			if (event.event_type !== 'merchant_protocol_mix_changed') continue;
			addSwitch(rows, switchFromRecord(event.data, event.round_num));
		}
		return Array.from(rows.values())
			.sort((a, b) => b.round - a.round || a.merchant.localeCompare(b.merchant))
			.slice(0, 6);
	}

	function addSwitch(rows: Map<string, MerchantSwitchRow>, row: MerchantSwitchRow | null) {
		if (!row) return;
		rows.set(`${row.round}:${row.merchantId}:${row.action}:${row.protocol}`, row);
	}

	function switchFromRecord(value: unknown, fallbackRound?: number): MerchantSwitchRow | null {
		const record = asRecord(value);
		if (!record) return null;
		const protocol = textFrom(record.protocol);
		if (!protocol) return null;
		const merchantId = textFrom(record.merchant_id) ?? textFrom(record.merchant) ?? 'merchant';
		return {
			merchantId,
			merchant: textFrom(record.merchant) ?? merchantId,
			action: textFrom(record.action) ?? 'changed',
			protocol,
			round: Math.trunc(numberFrom(record.round, record.round_num, fallbackRound) ?? 0),
			reason: textFrom(record.reason) ?? 'unknown',
			evidence: asRecord(record.evidence) ?? {},
		};
	}

	function evidenceItems(evidence: Evidence) {
		const keys = [
			...evidenceOrder.filter((key) => key in evidence),
			...Object.keys(evidence)
				.filter((key) => !evidenceOrder.includes(key))
				.sort(),
		];
		return keys.slice(0, 6).map((key) => ({
			label: formatLabel(key),
			value: formatEvidenceValue(key, evidence[key]),
		}));
	}

	function formatEvidenceValue(key: string, value: unknown) {
		const numeric = numberFrom(value);
		if (typeof value === 'boolean') return value ? 'yes' : 'no';
		if (key.endsWith('_cents') && numeric != null) return money(numeric);
		if (numeric != null) return Math.abs(numeric) >= 10 ? numeric.toFixed(0) : numeric.toFixed(2);
		return textFrom(value) ?? 'n/a';
	}

	function money(cents: number) {
		const amount = cents / 100;
		if (Math.abs(amount) >= 1000) {
			return amount.toLocaleString('en-US', {
				style: 'currency',
				currency: 'USD',
				maximumFractionDigits: 0,
			});
		}
		return amount.toLocaleString('en-US', {
			style: 'currency',
			currency: 'USD',
			minimumFractionDigits: 2,
			maximumFractionDigits: 2,
		});
	}

	function signedMoney(cents: number) {
		return `${cents >= 0 ? '+' : ''}${money(cents)}`;
	}

	function pct(value: number | null) {
		return value == null ? 'n/a' : `${(value * 100).toFixed(0)}%`;
	}

	function barWidth(value: number, max: number) {
		return `${Math.max(2, Math.min(100, (Math.abs(value) / max) * 100)).toFixed(1)}%`;
	}

	function protocolColor(protocol: string) {
		return PROTOCOL_COLORS[protocol.toLowerCase()] ?? '#71717a';
	}

	function reasonClass(reason: string) {
		return reason === 'ecosystem_evidence' ? 'reason-ecosystem' : 'reason-rail';
	}

	function formatLabel(value: string) {
		return value.replaceAll('_', ' ');
	}

	function asRecord(value: unknown): Record<string, unknown> | null {
		if (typeof value !== 'object' || value == null || Array.isArray(value)) return null;
		return value as Record<string, unknown>;
	}

	function textFrom(...values: unknown[]) {
		for (const value of values) {
			if (typeof value === 'string' && value.trim()) return value.trim();
			if (typeof value === 'number' || typeof value === 'boolean') return String(value);
		}
		return null;
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
</script>

<div class="economy-observability">
	<section class="panel route-panel">
		<div class="panel-heading">
			<div>
				<div class="eyebrow">Route Ledger</div>
				<h3>Reserved Principal</h3>
			</div>
			<div class="panel-total">
				<span>{money(routeTotalCents)}</span>
				<small>{routeRows.length} routes</small>
			</div>
		</div>

		<div class="route-list">
			{#each routeRows.slice(0, 5) as row}
				<div class="route-row">
					<div class="route-line">
						<span class="route-name">{row.route}</span>
						<strong>{money(row.usageCents)}</strong>
					</div>
					<div class="usage-track" aria-hidden="true">
						<span style={`width:${barWidth(row.usageCents, routeMaxCents)}`}></span>
					</div>
					<div class="mix-line">
						<span>{row.attempts} route-mix attempts</span>
						<div class="mix-chips">
							{#each row.protocols.slice(0, 4) as part}
								<span class="mix-chip" style={`border-color:${protocolColor(part.protocol)}; color:${protocolColor(part.protocol)}`}>
									{part.protocol.toUpperCase()} {part.count}
								</span>
							{:else}
								<span class="muted">No attempt mix</span>
							{/each}
						</div>
					</div>
				</div>
			{:else}
				<div class="empty-line">No reserved route principal recorded.</div>
			{/each}
		</div>
	</section>

	<section class="panel rail-panel">
		<div class="panel-heading">
			<div>
				<div class="eyebrow">Rail P&amp;L</div>
				<h3>Margin Drift</h3>
			</div>
			<div class="panel-note">final margin, per-round history</div>
		</div>

		<div class="rail-list">
			{#each railRows.slice(0, 5) as row}
				<div class="rail-row">
					<div class="rail-protocol">
						<span class="protocol-dot" style={`background:${protocolColor(row.protocol)}`}></span>
						<span>{row.protocol.toUpperCase()}</span>
					</div>
					<div class="rail-bar" aria-hidden="true">
						<span
							class:positive={row.marginCents >= 0}
							class:negative={row.marginCents < 0}
							style={`width:${barWidth(row.marginCents, railMaxAbs)}`}
						></span>
					</div>
					<div class="rail-values">
						<strong class:positive-text={row.marginCents >= 0} class:negative-text={row.marginCents < 0}>
							{money(row.marginCents)}
						</strong>
						<small>{signedMoney(row.deltaCents)} · {row.snapshots || 1} snapshots · {row.routeAttempts} attempts · rel {pct(row.reliability)}</small>
					</div>
				</div>
			{:else}
				<div class="empty-line">No rail margin snapshots recorded.</div>
			{/each}
		</div>
	</section>

	<section class="panel switch-panel">
		<div class="panel-heading">
			<div>
				<div class="eyebrow">Merchant Switches</div>
				<h3>Reason Evidence</h3>
			</div>
			<div class="panel-note">{switchRows.length} recent</div>
		</div>

		<div class="switch-list">
			{#each switchRows as row}
				<div class="switch-row">
					<div class="switch-main">
						<span class="round">R{row.round}</span>
						<strong>{row.merchant}</strong>
						<span>{formatLabel(row.action)} {row.protocol.toUpperCase()}</span>
						<span class={`reason ${reasonClass(row.reason)}`}>{formatLabel(row.reason)}</span>
					</div>
					<div class="evidence-line">
						{#each evidenceItems(row.evidence) as item}
							<span>{item.label}: {item.value}</span>
						{:else}
							<span class="muted">No structured evidence</span>
						{/each}
					</div>
				</div>
			{:else}
				<div class="empty-line">No merchant protocol switches recorded.</div>
			{/each}
		</div>
	</section>
</div>

<style>
	.economy-observability {
		display: grid;
		grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
		gap: 12px;
		margin-bottom: 16px;
	}

	.panel {
		min-width: 0;
		background: var(--bg-2);
		border: 1px solid var(--bd);
		border-radius: 6px;
		padding: 14px;
	}

	.switch-panel {
		grid-column: 1 / -1;
	}

	.panel-heading {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 14px;
		margin-bottom: 12px;
	}

	.eyebrow,
	.panel-note,
	.panel-total small {
		font-family: var(--mono);
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--tx-3);
	}

	h3 {
		margin: 2px 0 0;
		font-size: 15px;
		font-weight: 650;
		color: var(--tx-1);
	}

	.panel-total {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 2px;
		font-family: var(--mono);
	}

	.panel-total span {
		font-size: 18px;
		font-weight: 800;
		color: var(--tx-1);
	}

	.route-list,
	.rail-list,
	.switch-list {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.route-row,
	.rail-row,
	.switch-row {
		min-width: 0;
		border-top: 1px solid var(--bg-3);
		padding-top: 10px;
	}

	.route-row:first-child,
	.rail-row:first-child,
	.switch-row:first-child {
		border-top: none;
		padding-top: 0;
	}

	.route-line,
	.mix-line,
	.switch-main {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}

	.route-line {
		justify-content: space-between;
		font-family: var(--mono);
		font-size: 12px;
	}

	.route-name,
	.switch-main strong {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.route-line strong,
	.rail-values strong {
		font-family: var(--mono);
		font-size: 13px;
	}

	.usage-track,
	.rail-bar {
		height: 6px;
		background: var(--bg-0);
		border-radius: 3px;
		overflow: hidden;
		margin: 7px 0;
	}

	.usage-track span,
	.rail-bar span {
		display: block;
		height: 100%;
		border-radius: 3px;
		background: var(--mpp);
	}

	.mix-line {
		justify-content: space-between;
		color: var(--tx-3);
		font-family: var(--mono);
		font-size: 10px;
	}

	.mix-chips,
	.evidence-line {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		min-width: 0;
	}

	.mix-chip,
	.reason,
	.evidence-line span {
		border: 1px solid var(--bd);
		border-radius: 3px;
		padding: 2px 5px;
		font-family: var(--mono);
		font-size: 10px;
		line-height: 1.3;
		white-space: nowrap;
	}

	.rail-row {
		display: grid;
		grid-template-columns: 74px minmax(72px, 1fr) minmax(130px, 1.2fr);
		align-items: center;
		gap: 10px;
	}

	.rail-protocol {
		display: flex;
		align-items: center;
		gap: 7px;
		font-family: var(--mono);
		font-size: 11px;
		font-weight: 800;
	}

	.protocol-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex: 0 0 auto;
	}

	.rail-bar {
		margin: 0;
	}

	.rail-bar .positive {
		background: var(--x402);
	}

	.rail-bar .negative {
		background: var(--ap2);
	}

	.rail-values {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 2px;
		min-width: 0;
	}

	.rail-values small {
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--mono);
		font-size: 10px;
		color: var(--tx-3);
	}

	.positive-text {
		color: var(--x402);
	}

	.negative-text {
		color: var(--ap2);
	}

	.switch-main {
		font-family: var(--mono);
		font-size: 11px;
		color: var(--tx-2);
	}

	.round {
		flex: 0 0 auto;
		color: var(--tx-3);
	}

	.reason {
		margin-left: auto;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		font-weight: 800;
	}

	.reason-ecosystem {
		color: var(--x402);
		border-color: color-mix(in srgb, var(--x402) 45%, var(--bd));
		background: color-mix(in srgb, var(--x402) 12%, transparent);
	}

	.reason-rail {
		color: var(--atxp);
		border-color: color-mix(in srgb, var(--atxp) 45%, var(--bd));
		background: color-mix(in srgb, var(--atxp) 12%, transparent);
	}

	.evidence-line {
		margin-top: 7px;
		padding-left: 32px;
		color: var(--tx-3);
	}

	.empty-line,
	.muted {
		font-family: var(--mono);
		font-size: 11px;
		color: var(--tx-3);
	}

	@media (max-width: 1100px) {
		.economy-observability {
			grid-template-columns: 1fr;
		}

		.switch-panel {
			grid-column: auto;
		}
	}

	@media (max-width: 640px) {
		.panel-heading,
		.route-line,
		.mix-line,
		.switch-main {
			align-items: flex-start;
			flex-direction: column;
		}

		.panel-total,
		.rail-values {
			align-items: flex-start;
		}

		.rail-row {
			grid-template-columns: 1fr;
		}

		.reason {
			margin-left: 0;
		}

		.evidence-line {
			padding-left: 0;
		}
	}
</style>
