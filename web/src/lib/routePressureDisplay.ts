import type { RoutePressureSummary } from '$lib/stores/simulation.svelte';

export interface RoutePressureDisplayRow {
	route: string;
	usageCents: number;
	capacityRatio: number;
	pressureRounds: number;
	level: string;
	reason: string | null;
	primitive: string;
	failureCount: number | null;
	merchant: string | null;
	domains: string;
	protocols: string[];
	isTreasuryNoRoute: boolean;
	fundingContext: string | null;
}

const NO_FEASIBLE_REBALANCE_ROUTE = 'no_feasible_rebalance_route';

export function buildRoutePressureRows(summaries: RoutePressureSummary[]): RoutePressureDisplayRow[] {
	return summaries
		.map((summary) => {
			const route = textFrom(summary.route_id);
			if (!route) return null;

			const source = textFrom(summary.source_domain) ?? 'unknown';
			const target = textFrom(summary.target_domain) ?? 'unknown';
			const primitive = textFrom(summary.primitive) ?? 'unknown';
			const reason = textFrom(summary.reason, summary.error);
			const failureCount = numberFrom(summary.failure_count);
			const usageCents = nonNegativeNumber(summary.total_usage_cents);
			const protocols = Array.isArray(summary.protocols)
				? summary.protocols.flatMap((protocol) => {
					const label = textFrom(protocol);
					return label ? [label] : [];
				})
				: [];
			const isTreasuryNoRoute = primitive === 'treasury_rebalance'
				&& reason === NO_FEASIBLE_REBALANCE_ROUTE;

			const row = {
				route,
				usageCents,
				capacityRatio: nonNegativeNumber(summary.max_capacity_ratio),
				pressureRounds: wholeNonNegative(summary.pressure_rounds),
				level: textFrom(summary.last_pressure_level) ?? 'unknown',
				reason,
				primitive,
				failureCount: failureCount == null ? null : wholeNonNegative(failureCount),
				merchant: textFrom(summary.merchant, summary.merchant_id),
				domains: `${source} to ${target}`,
				protocols,
				isTreasuryNoRoute,
				fundingContext: null as string | null,
			};
			row.fundingContext = fundingContext(row);
			return row;
		})
		.filter((row): row is RoutePressureDisplayRow => row != null)
		.sort((a, b) => {
			const aNoRoute = a.reason === NO_FEASIBLE_REBALANCE_ROUTE ? 1 : 0;
			const bNoRoute = b.reason === NO_FEASIBLE_REBALANCE_ROUTE ? 1 : 0;
			return bNoRoute - aNoRoute
				|| b.capacityRatio - a.capacityRatio
				|| (b.failureCount ?? 0) - (a.failureCount ?? 0)
				|| b.usageCents - a.usageCents;
		});
}

export function buildNoRoutePressureRows(
	summaries: RoutePressureSummary[],
): RoutePressureDisplayRow[] {
	return buildRoutePressureRows(summaries)
		.filter((row) => row.reason === NO_FEASIBLE_REBALANCE_ROUTE || (row.failureCount ?? 0) > 0)
		.sort((a, b) =>
			b.capacityRatio - a.capacityRatio
			|| (b.failureCount ?? 0) - (a.failureCount ?? 0)
			|| b.pressureRounds - a.pressureRounds
		);
}

export function formatRoutePressureLabel(value: string) {
	return value.replaceAll('_', ' ');
}

function fundingContext(row: Omit<RoutePressureDisplayRow, 'fundingContext'>): string | null {
	if (!row.isTreasuryNoRoute && (row.failureCount ?? 0) <= 0) return null;
	const parts = [
		row.primitive === 'treasury_rebalance' ? 'treasury rebalance' : formatRoutePressureLabel(row.primitive),
		row.usageCents > 0 ? `${row.usageCents} cents` : null,
		row.domains,
		row.protocols.length > 0 ? `via ${row.protocols.join(', ')}` : null,
		row.failureCount != null ? `${row.failureCount} failed` : null,
		row.merchant,
	];
	return parts.filter((part): part is string => typeof part === 'string' && part.length > 0).join(' · ');
}

function textFrom(...values: unknown[]) {
	for (const value of values) {
		if (typeof value !== 'string') continue;
		const trimmed = value.trim();
		if (trimmed) return trimmed;
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

function nonNegativeNumber(value: unknown) {
	return Math.max(0, numberFrom(value) ?? 0);
}

function wholeNonNegative(value: unknown) {
	return Math.max(0, Math.trunc(numberFrom(value) ?? 0));
}
