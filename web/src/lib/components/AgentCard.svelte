<script>
  import ProtocolBadge from './ProtocolBadge.svelte';

  /**
   * @type {{
   *   agent: {
   *     agent_id: string,
   *     name: string,
   *     budget: number,
   *     spent: number,
   *     price_sensitivity: number,
   *     brand_loyalty: number,
   *     risk_tolerance: number,
   *     preferred_categories: string[],
   *     protocol_preference?: string,
   *     state: string,
   *   }
   * }}
   */
  let { agent } = $props();

  const avatarColors = [
    '#3b82f6', '#ef4444', '#10b981', '#8b5cf6',
    '#f59e0b', '#ec4899', '#06b6d4', '#f97316',
  ];

  let color = $derived(() => {
    const name = agent?.name ?? '';
    let hash = 0;
    for (let i = 0; i < name.length; i++) {
      hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    return avatarColors[Math.abs(hash) % avatarColors.length];
  });

  let letter = $derived((agent?.name ?? 'A')[0].toUpperCase());
  let spentPct = $derived(agent?.budget > 0 ? Math.min((agent.spent / agent.budget) * 100, 100) : 0);

  let budgetLabel = $derived(() => {
    const fmt = (v) =>
      (v / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
    return `${fmt(agent?.spent ?? 0)} / ${fmt(agent?.budget ?? 0)}`;
  });

  const paramDefs = [
    { key: 'price_sensitivity', label: 'Price Sens.' },
    { key: 'brand_loyalty', label: 'Brand Loyalty' },
    { key: 'risk_tolerance', label: 'Risk Tol.' },
  ];
</script>

<div class="agent-card">
  <!-- Header -->
  <div class="card-header">
    <div class="avatar" style:background={color()}>
      {letter}
    </div>
    <div class="header-text">
      <span class="agent-name">{agent?.name ?? 'Unknown'}</span>
      <span class="agent-id">{agent?.agent_id ?? ''}</span>
    </div>
    {#if agent?.state}
      <span class="state-tag">{agent.state}</span>
    {/if}
  </div>

  <!-- Budget bar -->
  <div class="budget-section">
    <div class="budget-label-row">
      <span class="budget-label">BUDGET</span>
      <span class="budget-value">{budgetLabel()}</span>
    </div>
    <div class="budget-track">
      <div
        class="budget-fill"
        style:width="{spentPct}%"
        style:background={spentPct > 80 ? '#ef4444' : spentPct > 50 ? '#f59e0b' : '#10b981'}
      ></div>
    </div>
    <span class="budget-pct">{spentPct.toFixed(1)}% spent</span>
  </div>

  <!-- Behavioral params -->
  <div class="params-row">
    {#each paramDefs as param}
      <div class="param">
        <span class="param-label">{param.label}</span>
        <span class="param-value">{(agent?.[param.key] ?? 0).toFixed(2)}</span>
      </div>
    {/each}
  </div>

  <!-- Categories -->
  {#if agent?.preferred_categories?.length}
    <div class="categories">
      {#each agent.preferred_categories as cat}
        <span class="cat-tag">{cat}</span>
      {/each}
    </div>
  {/if}

  <!-- Protocol preference -->
  {#if agent?.protocol_preference}
    <div class="protocol-row">
      <span class="pref-label">Preferred</span>
      <ProtocolBadge protocol={agent.protocol_preference} />
    </div>
  {/if}
</div>

<style>
  .agent-card {
    background: var(--bg-1, #111);
    border: 1px solid var(--bd, #333);
    border-radius: 8px;
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .avatar {
    width: 34px;
    height: 34px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--sans, sans-serif);
    font-size: 15px;
    font-weight: 700;
    color: #fff;
    flex-shrink: 0;
  }

  .header-text {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
  }

  .agent-name {
    font-family: var(--sans, sans-serif);
    font-size: 14px;
    font-weight: 600;
    color: var(--tx-1, #eee);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .agent-id {
    font-family: var(--mono, monospace);
    font-size: 10px;
    color: var(--tx-3, #666);
  }

  .state-tag {
    font-family: var(--mono, monospace);
    font-size: 10px;
    color: var(--tx-3, #666);
    background: var(--bg-2, #1a1a1a);
    border: 1px solid var(--bd, #333);
    padding: 2px 7px;
    border-radius: 4px;
    flex-shrink: 0;
    white-space: nowrap;
  }

  /* Budget */
  .budget-section {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .budget-label-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .budget-label {
    font-family: var(--mono, monospace);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
    color: var(--tx-3, #666);
  }

  .budget-value {
    font-family: var(--mono, monospace);
    font-size: 11px;
    color: var(--tx-2, #aaa);
  }

  .budget-track {
    height: 4px;
    background: var(--bg-3, #222);
    border-radius: 2px;
    overflow: hidden;
  }

  .budget-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.4s ease;
  }

  .budget-pct {
    font-family: var(--mono, monospace);
    font-size: 10px;
    color: var(--tx-3, #666);
    text-align: right;
  }

  /* Params */
  .params-row {
    display: flex;
    gap: 8px;
  }

  .param {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    background: var(--bg-2, #1a1a1a);
    border: 1px solid var(--bd, #333);
    border-radius: 4px;
    padding: 6px 4px;
  }

  .param-label {
    font-family: var(--mono, monospace);
    font-size: 8px;
    font-weight: 600;
    letter-spacing: 0.05em;
    color: var(--tx-3, #666);
    text-transform: uppercase;
    text-align: center;
  }

  .param-value {
    font-family: var(--mono, monospace);
    font-size: 13px;
    font-weight: 600;
    color: var(--tx-1, #eee);
  }

  /* Categories */
  .categories {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }

  .cat-tag {
    font-family: var(--mono, monospace);
    font-size: 10px;
    color: var(--tx-2, #aaa);
    background: var(--bg-2, #1a1a1a);
    border: 1px solid var(--bd, #333);
    padding: 2px 7px;
    border-radius: 9999px;
  }

  /* Protocol row */
  .protocol-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .pref-label {
    font-family: var(--mono, monospace);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
    color: var(--tx-3, #666);
    text-transform: uppercase;
  }
</style>
