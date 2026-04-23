export type TimelineEvent = Record<string, unknown> & { type?: unknown };

function textValue(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'string') {
      const trimmed = value.trim();
      if (trimmed) return trimmed;
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
      return String(value);
    }
  }
  return null;
}

function numberValue(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function recordValue(value: unknown) {
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function textField(evt: TimelineEvent, ...keys: string[]) {
  const data = recordValue(evt.data);
  for (const key of keys) {
    const value = textValue(evt[key], data?.[key]);
    if (value) return value;
  }
  return null;
}

function numberField(evt: TimelineEvent, ...keys: string[]) {
  const data = recordValue(evt.data);
  for (const key of keys) {
    const value = numberValue(evt[key]) ?? numberValue(data?.[key]);
    if (value != null) return value;
  }
  return null;
}

function formatAmount(cents?: unknown) {
  const amount = numberValue(cents);
  if (amount == null) return '--';
  return (amount / 100).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
  });
}

function formatRatio(value: number) {
  return `${(value * 100).toFixed(value >= 1 ? 0 : 1)}%`;
}

function formatLabel(value: string) {
  return value.replaceAll('_', ' ');
}

export function timelineMetaItems(evt: TimelineEvent) {
  const items = [
    ['merchant', textField(evt, 'merchant', 'merchant_name')],
    ['from', textField(evt, 'source_domain')],
    ['to', textField(evt, 'target_domain')],
    ['mode', textField(evt, 'primitive')],
    ['route', textField(evt, 'route_id')],
    ['flow', textField(evt, 'workload_type')],
  ].flatMap(([label, value]) => value ? [`${label}: ${value}`] : []);

  const trustAfter = numberValue(evt.trust_after);
  if (trustAfter != null) {
    const trustBefore = numberValue(evt.trust_before);
    items.push(`trust: ${trustBefore == null ? '--' : trustBefore.toFixed(2)} -> ${trustAfter.toFixed(2)}`);
  }

  const driver = textField(evt, 'trust_driver');
  if (driver) {
    items.push(`driver: ${formatLabel(driver)}`);
  }

  const outcome = textField(evt, 'outcome');
  if (outcome) {
    items.push(`outcome: ${formatLabel(outcome)}`);
  }

  const pressureLevel = textField(evt, 'pressure_level', 'last_pressure_level');
  if (pressureLevel) {
    items.push(`pressure: ${formatLabel(pressureLevel)}`);
  }

  const capacityRatio = numberField(evt, 'capacity_ratio', 'max_capacity_ratio');
  if (capacityRatio != null) {
    items.push(`capacity: ${formatRatio(capacityRatio)}`);
  }

  const ecosystemPressure = numberField(evt, 'ecosystem_pressure');
  if (ecosystemPressure != null && ecosystemPressure > 0) {
    items.push(`stress: ${formatRatio(ecosystemPressure)}`);
  }

  const preferredRatio = numberField(evt, 'preferred_ratio', 'last_preferred_ratio', 'min_preferred_ratio');
  if (preferredRatio != null) {
    items.push(`preferred: ${formatRatio(preferredRatio)}`);
  }

  const shortfall = numberField(evt, 'preferred_shortfall_cents', 'max_preferred_shortfall_cents');
  if (shortfall != null && shortfall > 0) {
    items.push(`shortfall: ${formatAmount(shortfall)}`);
  }

  return items;
}
