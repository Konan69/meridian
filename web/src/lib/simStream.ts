import type {
  AgentMemoryEvent,
  BalanceSnapshot,
  EconomyWorldEvent,
  ProtoMetrics,
  ProtocolEcosystem,
  SimEvent,
} from './stores/simulation.svelte';

export type TrustSummary = Record<string, { avg: number; min: number; max: number }>;

type JsonRecord = Record<string, unknown>;

export type ParseResult =
  | { ok: true; event: SimEvent }
  | { ok: false; reason: string; line: string };

export function splitNdjsonChunk(buffer: string, chunk: string) {
  const lines = `${buffer}${chunk}`.split('\n');
  const nextBuffer = lines.pop() ?? '';
  return {
    lines: lines.map((line) => line.trim()).filter(Boolean),
    buffer: nextBuffer,
  };
}

export function finalNdjsonLine(buffer: string) {
  const line = buffer.trim();
  return line.length > 0 ? line : null;
}

export function parseSimulationEvent(line: string): ParseResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(line);
  } catch {
    return { ok: false, reason: 'invalid_json', line };
  }

  const record = asRecord(parsed);
  if (!record) {
    return { ok: false, reason: 'not_object', line };
  }

  const type = eventType(record);
  if (!type) {
    return { ok: false, reason: 'missing_type', line };
  }

  return { ok: true, event: { ...record, type } };
}

export function normalizeTimelineEvent(event: SimEvent): SimEvent {
  const round = numberFrom(event.round, event.round_num);
  return {
    ...event,
    type: event.type,
    ...(round == null ? {} : { round, round_num: round }),
  };
}

export function describeStreamEvent(event: SimEvent) {
  const subject =
    textFrom(event.agent) ??
    textFrom(event.agent_name) ??
    textFrom(event.summary) ??
    textFrom(event.reason) ??
    '';
  const detail =
    textFrom(event.product) ??
    textFrom(event.product_name) ??
    textFrom(event.event_type) ??
    '';
  const protocol = textFrom(event.protocol) ?? '';
  return [subject, detail, protocol].filter(Boolean).join(' ');
}

export function normalizeAgentMemoryEvent(event: SimEvent): AgentMemoryEvent | null {
  if (event.type !== 'agent_memory') return null;

  const agentId = textFrom(event.agent_id) ?? textFrom(event.agent) ?? 'agent_unknown';
  const trustBefore = numberFrom(event.trust_before, event.trust) ?? 0;

  return {
    round_num: wholeNumberFrom(event.round_num, event.round) ?? 0,
    agent_id: agentId,
    agent_name: textFrom(event.agent_name) ?? textFrom(event.agent) ?? agentId,
    event_type: textFrom(event.event_type) ?? 'protocol_experience',
    protocol: textFrom(event.protocol) ?? 'unknown',
    workload_type: textFrom(event.workload_type) ?? 'unknown',
    sentiment_delta: numberFrom(event.sentiment_delta) ?? 0,
    trust_before: trustBefore,
    trust_after: numberFrom(event.trust_after, event.trust) ?? trustBefore,
    amount_cents: wholeNumberFrom(event.amount_cents) ?? 0,
    merchant_id: nullableText(event.merchant_id),
    merchant_name: nullableText(event.merchant_name) ?? nullableText(event.merchant),
    product_name: nullableText(event.product_name) ?? nullableText(event.product),
    route_id: nullableText(event.route_id),
    reason: textFrom(event.reason) ?? textFrom(event.summary) ?? 'memory_event',
  };
}

export function normalizeAgentMemoryEvents(value: unknown) {
  if (!Array.isArray(value)) return null;
  return value.flatMap((item) => {
    const record = asRecord(item);
    const memory = record ? normalizeAgentMemoryEvent({ ...record, type: 'agent_memory' }) : null;
    return memory ? [memory] : [];
  });
}

export function normalizeWorldEvent(event: SimEvent): EconomyWorldEvent | null {
  if (event.type !== 'world_event') return null;

  const summary =
    textFrom(event.summary) ??
    textFrom(event.reason) ??
    textFrom(event.event_type) ??
    'world_event';

  return {
    round_num: wholeNumberFrom(event.round_num, event.round) ?? 0,
    event_type: textFrom(event.event_type) ?? 'world_event',
    summary,
    actor_id: nullableText(event.actor_id),
    protocol: nullableText(event.protocol),
    data: asRecord(event.data) ?? {},
  };
}

export function normalizeWorldEvents(value: unknown) {
  if (!Array.isArray(value)) return null;
  return value.flatMap((item) => {
    const record = asRecord(item);
    const worldEvent = record ? normalizeWorldEvent({ ...record, type: 'world_event' }) : null;
    return worldEvent ? [worldEvent] : [];
  });
}

export function normalizeTrustSummary(value: unknown): TrustSummary {
  const record = asRecord(value);
  if (!record) return {};

  return Object.fromEntries(
    Object.entries(record).flatMap(([protocol, raw]) => {
      const stats = asRecord(raw);
      if (!stats) return [];
      const avg = numberFrom(stats.avg);
      const min = numberFrom(stats.min);
      const max = numberFrom(stats.max);
      if (avg == null && min == null && max == null) return [];
      return [[protocol, { avg: avg ?? 0, min: min ?? avg ?? 0, max: max ?? avg ?? 0 }]];
    }),
  );
}

export function normalizeProtocolSummaries(value: unknown): ProtoMetrics[] {
  const record = asRecord(value);
  if (!record) return [];

  return Object.entries(record)
    .flatMap(([protocol, raw]) => {
      const item = asRecord(raw);
      if (!item) return [];
      return [{
        protocol: textFrom(item.protocol) ?? protocol,
        total_transactions: wholeNumberFrom(item.total_transactions) ?? 0,
        successful_transactions: wholeNumberFrom(item.successful_transactions) ?? 0,
        failed_transactions: wholeNumberFrom(item.failed_transactions) ?? 0,
        total_volume_cents: wholeNumberFrom(item.total_volume_cents) ?? 0,
        total_fees_cents: wholeNumberFrom(item.total_fees_cents) ?? 0,
        avg_settlement_ms: numberFrom(item.avg_settlement_ms) ?? 0,
        avg_authorization_ms: numberFrom(item.avg_authorization_ms) ?? 0,
        micropayment_count: wholeNumberFrom(item.micropayment_count) ?? 0,
      }];
    })
    .sort((a, b) => a.avg_settlement_ms - b.avg_settlement_ms);
}

export function normalizeEcosystemSummary(value: unknown): Record<string, ProtocolEcosystem> {
  const record = asRecord(value);
  if (!record) return {};

  return Object.fromEntries(
    Object.entries(record).flatMap(([protocol, raw]) => {
      const item = asRecord(raw);
      if (!item) return [];
      return [[protocol, {
        merchant_count: wholeNumberFrom(item.merchant_count) ?? 0,
        network_effect: numberFrom(item.network_effect) ?? 0,
        congestion: numberFrom(item.congestion) ?? 0,
        operator_margin_cents: wholeNumberFrom(item.operator_margin_cents) ?? 0,
        reliability: numberFrom(item.reliability) ?? undefined,
        route_mix: normalizeNumberRecord(item.route_mix),
      }]];
    }),
  );
}

export function normalizeBalanceSnapshots(value: unknown): BalanceSnapshot[] {
  if (!Array.isArray(value)) return [];

  return value.flatMap((raw) => {
    const item = asRecord(raw);
    if (!item) return [];
    return [{
      owner_kind: textFrom(item.owner_kind) ?? 'unknown',
      owner_id: textFrom(item.owner_id) ?? 'unknown',
      domain: textFrom(item.domain) ?? 'unknown',
      available_cents: wholeNumberFrom(item.available_cents) ?? 0,
      reserved_cents: wholeNumberFrom(item.reserved_cents) ?? 0,
      pending_in_cents: wholeNumberFrom(item.pending_in_cents) ?? 0,
      pending_out_cents: wholeNumberFrom(item.pending_out_cents) ?? 0,
    }];
  });
}

export function normalizeNumberRecord(value: unknown): Record<string, number> {
  const record = asRecord(value);
  if (!record) return {};

  return Object.fromEntries(
    Object.entries(record).flatMap(([key, raw]) => {
      const value = numberFrom(raw);
      return value == null ? [] : [[key, value]];
    }),
  );
}

export function normalizeNestedNumberRecord(value: unknown): Record<string, Record<string, number>> {
  const record = asRecord(value);
  if (!record) return {};

  return Object.fromEntries(
    Object.entries(record).flatMap(([key, raw]) => {
      const nested = normalizeNumberRecord(raw);
      return Object.keys(nested).length === 0 ? [] : [[key, nested]];
    }),
  );
}

export function normalizeNumberArrayRecord(value: unknown): Record<string, number[]> {
  const record = asRecord(value);
  if (!record) return {};

  return Object.fromEntries(
    Object.entries(record).flatMap(([key, raw]) => {
      if (!Array.isArray(raw)) return [];
      const values = raw.flatMap((item) => {
        const value = numberFrom(item);
        return value == null ? [] : [value];
      });
      return values.length === 0 ? [] : [[key, values]];
    }),
  );
}

export function numberFrom(...values: unknown[]) {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}

function wholeNumberFrom(...values: unknown[]) {
  const value = numberFrom(...values);
  return value == null ? null : Math.trunc(value);
}

function eventType(record: JsonRecord) {
  const explicit = textFrom(record.type);
  if (explicit) return explicit;
  if (asRecord(record.protocol_summaries) || Array.isArray(record.agent_memory_log)) {
    return 'simulation_complete';
  }
  if (asRecord(record.trust_summary)) return 'trust_snapshot';
  if (record.trust_after != null && (record.agent_name != null || record.agent != null)) {
    return 'agent_memory';
  }
  if (record.summary != null || record.event_type != null) return 'world_event';
  return null;
}

function asRecord(value: unknown): JsonRecord | null {
  if (typeof value !== 'object' || value == null || Array.isArray(value)) return null;
  return value as JsonRecord;
}

function textFrom(value: unknown) {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return null;
}

function nullableText(value: unknown) {
  return value == null ? null : textFrom(value);
}
