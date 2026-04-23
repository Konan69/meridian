<script lang="ts">
  import ProtocolBadge from './ProtocolBadge.svelte';
  import { getAvatarColor } from '$lib/constants';
  import { timelineMetaItems, type TimelineEvent } from '$lib/timelineMetadata';

  let { events = [] }: { events: TimelineEvent[] } = $props();

  let feedEl = $state<HTMLDivElement | null>(null);

  $effect(() => {
    const _len = events.length;
    if (feedEl) {
      requestAnimationFrame(() => {
        if (feedEl) {
          feedEl.scrollTop = feedEl.scrollHeight;
        }
      });
    }
  });

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

  function formatAmount(cents?: unknown) {
    const amount = numberValue(cents);
    if (amount == null) return '--';
    return (amount / 100).toLocaleString('en-US', {
      style: 'currency',
      currency: 'USD',
    });
  }

  function formatFee(cents?: unknown) {
    const amount = numberValue(cents);
    if (amount == null || amount === 0) return '';
    return `fee ${formatAmount(amount)}`;
  }

  function formatTime(ts?: unknown) {
    const value = textValue(ts);
    if (!value) return '';
    try {
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) return value;
      return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return value;
    }
  }

  function actorName(evt: TimelineEvent) {
    return textValue(evt.agent, evt.agent_name) ?? 'World';
  }

  function actorInitial(evt: TimelineEvent) {
    return actorName(evt).slice(0, 1).toUpperCase() || 'W';
  }

  function eventType(evt: TimelineEvent) {
    return textValue(evt.type) ?? 'event';
  }

  function eventBody(evt: TimelineEvent) {
    return textValue(evt.product, evt.product_name, evt.summary, evt.reason, evt.event_type) ?? '--';
  }

  function roundLabel(evt: TimelineEvent) {
    const round = numberValue(evt.round) ?? numberValue(evt.round_num);
    return round == null ? '-' : String(Math.trunc(round));
  }

  const typeBadgeStyles = {
    CHECKOUT:  { bg: 'rgba(59,130,246,0.15)', color: '#3b82f6', border: 'rgba(59,130,246,0.3)' },
    PAYMENT:   { bg: 'rgba(16,185,129,0.15)', color: '#10b981', border: 'rgba(16,185,129,0.3)' },
    REFUND:    { bg: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: 'rgba(245,158,11,0.3)' },
    FAILED:    { bg: 'rgba(239,68,68,0.15)',   color: '#ef4444', border: 'rgba(239,68,68,0.3)' },
  };

  function badgeStyle(type?: unknown) {
    const key = textValue(type)?.toUpperCase() as keyof typeof typeBadgeStyles | undefined;
    const s = (key ? typeBadgeStyles[key] : undefined) ?? { bg: 'rgba(255,255,255,0.06)', color: 'var(--tx-2, #aaa)', border: 'var(--bd, #333)' };
    return `background:${s.bg}; color:${s.color}; border:1px solid ${s.border}`;
  }
</script>

<div class="timeline">
  <div class="timeline-header">
    <span class="timeline-title">EVENT TIMELINE</span>
    <span class="timeline-count">{events.length} events</span>
  </div>
  <div class="timeline-feed" bind:this={feedEl} aria-label="Event timeline" role="log">
    {#each events as evt, idx (idx)}
      {@const protocol = textValue(evt.protocol)}
      {@const meta = timelineMetaItems(evt)}
      {@const fee = formatFee(evt.fee_cents)}
      {@const time = formatTime(evt.timestamp)}
          <div class="event-card" style="animation-delay: {Math.min(idx * 30, 300)}ms">
        <div class="card-header">
          <div class="agent-info">
            <div class="avatar" style:background={getAvatarColor(actorName(evt))}>
              {actorInitial(evt)}
            </div>
            <span class="agent-name">{actorName(evt)}</span>
          </div>
          <div class="header-badges">
            {#if protocol}
              <ProtocolBadge {protocol} />
            {/if}
            <span class="type-badge" style={badgeStyle(evt.type)}>
              {eventType(evt).toUpperCase()}
            </span>
          </div>
        </div>

        <div class="card-body">
          <span class="product-name">{eventBody(evt)}</span>
          <span class="amount">{formatAmount(evt.amount_cents)}</span>
          {#if fee}
            <span class="fee">{fee}</span>
          {/if}
        </div>

        {#if meta.length > 0}
          <div class="card-meta">
            {#each meta as item}
              <span>{item}</span>
            {/each}
          </div>
        {/if}

        <div class="card-footer">
          <span class="round-tag">R{roundLabel(evt)}</span>
          {#if time}
            <span class="time-tag">{time}</span>
          {/if}
        </div>
      </div>
    {/each}

    {#if events.length === 0}
      <div class="empty-state">
        <div class="pulse-ring"></div>
        <span>Waiting for transactions...</span>
      </div>
    {/if}
  </div>
</div>

<style>
  .timeline {
    display: flex;
    flex-direction: column;
    background: var(--bg-0, #0a0a0a);
    border: 1px solid var(--bd, #333);
    border-radius: 8px;
    overflow: hidden;
    height: 100%;
  }

  .timeline-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    background: var(--bg-1, #111);
    border-bottom: 1px solid var(--bd, #333);
  }

  .timeline-title {
    font-family: var(--mono, monospace);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.1em;
    color: var(--tx-3, #666);
  }

  .timeline-count {
    font-family: var(--mono, monospace);
    font-size: 10px;
    color: var(--tx-3, #666);
  }

  .timeline-feed {
    flex: 1;
    overflow-y: auto;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    scrollbar-width: thin;
    scrollbar-color: #333 transparent;
  }

  .timeline-feed::-webkit-scrollbar {
    width: 4px;
  }

  .timeline-feed::-webkit-scrollbar-track {
    background: transparent;
  }

  .timeline-feed::-webkit-scrollbar-thumb {
    background: #333;
    border-radius: 2px;
  }

  .event-card {
    background: var(--bg-1, #111);
    border: 1px solid var(--bd, #333);
    border-radius: 6px;
    padding: 10px 12px;
    animation: card-enter 0.3s ease-out both;
  }

  @keyframes card-enter {
    from {
      opacity: 0;
      transform: translateY(20px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 8px;
  }

  .agent-info {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .avatar {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--sans, sans-serif);
    font-size: 12px;
    font-weight: 700;
    color: #fff;
    flex-shrink: 0;
  }

  .agent-name {
    font-family: var(--sans, sans-serif);
    font-size: 13px;
    font-weight: 600;
    color: var(--tx-1, #eee);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .header-badges {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }

  .type-badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 9999px;
    font-family: var(--mono, monospace);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.05em;
    white-space: nowrap;
  }

  .card-body {
    display: flex;
    align-items: baseline;
    gap: 10px;
    flex-wrap: wrap;
    padding: 0 0 8px 34px; /* indent past avatar */
  }

  .product-name {
    font-family: var(--sans, sans-serif);
    font-size: 13px;
    color: var(--tx-1, #eee);
  }

  .amount {
    font-family: var(--mono, monospace);
    font-size: 13px;
    font-weight: 600;
    color: #f59e0b;
  }

  .fee {
    font-family: var(--mono, monospace);
    font-size: 11px;
    color: var(--tx-3, #666);
  }

  .card-meta {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 4px 10px;
    padding: 0 0 8px 34px;
    font-family: var(--mono, monospace);
    font-size: 10px;
    color: var(--tx-3, #666);
  }

  .card-footer {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-left: 34px;
    font-family: var(--mono, monospace);
    font-size: 10px;
    color: var(--tx-3, #666);
  }

  .round-tag {
    background: var(--bg-2, #1a1a1a);
    padding: 1px 6px;
    border-radius: 3px;
    border: 1px solid var(--bd, #333);
  }

  .time-tag {
    color: var(--tx-3, #666);
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    padding: 40px 20px;
    color: var(--tx-3, #666);
    font-family: var(--mono, monospace);
    font-size: 12px;
  }

  .pulse-ring {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: 2px solid var(--tx-3, #666);
    animation: pulse 1.5s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 0.3; transform: scale(0.9); }
    50% { opacity: 1; transform: scale(1.1); }
  }
</style>
