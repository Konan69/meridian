export interface RouteScoreDriverDisplay {
	text: string;
	hasFiniteValue: boolean;
	fields: RouteScoreDriverField[];
}

export interface RouteScoreDriverField {
	label: string;
	value: string;
	available: boolean;
}

export function routeScoreDriverDisplay(
	score: unknown,
	pressurePenalty: unknown,
	sustainabilityBias: unknown,
): RouteScoreDriverDisplay | null {
	const fields = [
		{ label: 'score', value: finiteNumber(score), prefix: '' },
		{ label: 'pressure', value: finiteNumber(pressurePenalty), prefix: '' },
		{ label: 'sustain', value: finiteNumber(sustainabilityBias), prefix: '+' },
	];
	const inputs = [score, pressurePenalty, sustainabilityBias];
	const hasAnyInput = inputs.some((value) => value != null && value !== '');
	const hasInvalidInput = inputs.some((value) => value != null && value !== '' && finiteNumber(value) == null);
	const hasFiniteValue = fields.some((field) => field.value != null);
	const hasNonZeroValue = fields.some((field) => field.value != null && field.value !== 0);

	if (!hasAnyInput) return null;
	if (hasFiniteValue && !hasNonZeroValue && !hasInvalidInput) return null;

	return {
		hasFiniteValue,
		fields: fields.map((field) => ({
			label: field.label,
			value: formatDriverValue(field.value, field.prefix),
			available: field.value != null,
		})),
		text: fields
			.map((field) => `${field.label} ${formatDriverValue(field.value, field.prefix)}`)
			.join(' · '),
	};
}

function formatDriverValue(value: number | null, prefix: string): string {
	if (value == null) return 'n/a';
	if (prefix && value >= 0) return `${prefix}${value.toFixed(2)}`;
	return value.toFixed(2);
}

function finiteNumber(value: unknown): number | null {
	if (typeof value === 'number' && Number.isFinite(value)) return value;
	if (typeof value === 'string' && value.trim()) {
		const parsed = Number(value);
		if (Number.isFinite(parsed)) return parsed;
	}
	return null;
}
