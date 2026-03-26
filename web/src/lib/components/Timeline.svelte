<script>
  import ProtocolBadge from './ProtocolBadge.svelte';
  import { AVATAR_COLORS, getAvatarColor } from '$lib/constants';

  /**
   * @type {{
   *   events: Array<{
   *     type: string,
   *     agent: string,
   *     product: string,
   *     protocol: string,
   *     amount_cents: number,
   *     fee_cents: number,
   *     round: number,
   *     timestamp?: string
   *   }>
   * }}
   */
  let { events = [] } = $props();

  let feedEl = $state(null);

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

  function formatAmount(cents) {
    if (cents == null) return '--';
    return (cents / 100).toLocaleString('en-US', {
      style: 'currency',
      currency: 'USD',
    });
  }

  function formatFee(cents) {
    if (cents == null || cents === 0) return '';
    return `fee ${formatAmount(cents)}`;
  }

  function formatTime(ts) {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch {
      return ts;
    }
  }

  const typeBadgeStyles = {
    CHECKOUT:  { bg: 'rgba(59,130,246,0.15)', color: '#3b82f6', border: 'rgba(59,130,246,0.3)' },
    PAYMENT:   { bg: 'rgba(16,185,129,0.15)', color: '#10b981', border: 'rgba(16,185,129,0.3)' },
    REFUND:    { bg: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: 'rgba(245,158,11,0.3)' },
    FAILED:    { bg: 'rgba(239,68,68,0.15)',   color: '#ef4444', border: 'rgba(239,68,68,0.3)' },
  };

  function badgeStyle(type) {
    const s = typeBadgeStyles[type?.toUpperCase()] ?? { bg: 'rgba(255,255,255,0.06)', color: 'var(--tx-2, #aaa)', border: 'var(--bd, #333)' };
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
          <div class="event-card" style="animation-delay: {Math.min(idx * 30, 300)}ms">
        <div class="card-header">
          <div class="agent-info">
            <div class="avatar" style:background={getAvatarColor(evt.agent)}>
              {evt.agent ? evt.agent[0].toUpperCase() : 'A'}
            </div>
            <span class="agent-name">{evt.agent ?? 'Unknown'}</span>
          </div>
          <div class="header-badges">
            <ProtocolBadge protocol={evt.protocol} />
            <span class="type-badge" style={badgeStyle(evt.type)}>
              {evt.type?.toUpperCase() ?? 'EVENT'}
            </span>
          </div>
        </div>

        <div class="card-body">
          <span class="product-name">{evt.product ?? '--'}</span>
          <span class="amount">{formatAmount(evt.amount_cents)}</span>
          {#if evt.fee_cents}
            <span class="fee">{formatFee(evt.fee_cents)}</span>
          {/if}
        </div>

        <div class="card-footer">
          <span class="round-tag">R{evt.round ?? '-'}</span>
          {#if evt.timestamp}
            <span class="time-tag">{formatTime(evt.timestamp)}</span>
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
