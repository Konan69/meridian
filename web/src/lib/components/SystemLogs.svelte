<script>
  /** @type {{ logs: Array<{ time: string, message: string, level?: string }> }} */
  let { logs = [] } = $props();

  let logContainer = $state(null);

  $effect(() => {
    // Track logs length to auto-scroll on new entries
    const _len = logs.length;
    if (logContainer) {
      // Use requestAnimationFrame to scroll after DOM update
      requestAnimationFrame(() => {
        if (logContainer) {
          logContainer.scrollTop = logContainer.scrollHeight;
        }
      });
    }
  });

  function levelColor(level) {
    if (!level) return 'var(--tx-2, #aaa)';
    switch (level.toLowerCase()) {
      case 'error': return '#ef4444';
      case 'warn':
      case 'warning': return '#f59e0b';
      case 'info': return '#3b82f6';
      case 'success': return '#10b981';
      default: return 'var(--tx-2, #aaa)';
    }
  }
</script>

<div class="system-logs">
  <div class="log-header">
    <span class="log-title">SYSTEM LOG</span>
    <span class="log-count">{logs.length} entries</span>
  </div>
  <div class="log-content" bind:this={logContainer}>
    {#each logs as log, idx (idx)}
      <div class="log-line">
        <span class="log-time">{log.time}</span>
        <span class="log-level-dot" style:background={levelColor(log.level)}></span>
        <span class="log-msg" style:color={levelColor(log.level)}>{log.message}</span>
      </div>
    {/each}
    {#if logs.length === 0}
      <div class="log-empty">Waiting for events...</div>
    {/if}
  </div>
</div>

<style>
  .system-logs {
    background: #000;
    border: 1px solid var(--bd, #333);
    border-radius: 6px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .log-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    background: rgba(255, 255, 255, 0.03);
    border-bottom: 1px solid var(--bd, #333);
  }

  .log-title {
    font-family: var(--mono, monospace);
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.1em;
    color: var(--tx-3, #666);
    text-transform: uppercase;
  }

  .log-count {
    font-family: var(--mono, monospace);
    font-size: 10px;
    color: var(--tx-3, #666);
  }

  .log-content {
    max-height: 280px;
    overflow-y: auto;
    padding: 8px 0;
    scrollbar-width: thin;
    scrollbar-color: #333 transparent;
  }

  .log-content::-webkit-scrollbar {
    width: 4px;
  }

  .log-content::-webkit-scrollbar-track {
    background: transparent;
  }

  .log-content::-webkit-scrollbar-thumb {
    background: #333;
    border-radius: 2px;
  }

  .log-line {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 2px 12px;
    font-family: var(--mono, monospace);
    font-size: 11px;
    line-height: 1.5;
  }

  .log-line:hover {
    background: rgba(255, 255, 255, 0.03);
  }

  .log-time {
    color: #555;
    flex-shrink: 0;
    min-width: 70px;
  }

  .log-level-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    flex-shrink: 0;
    margin-top: 5px;
  }

  .log-msg {
    word-break: break-word;
  }

  .log-empty {
    padding: 20px 12px;
    text-align: center;
    font-family: var(--mono, monospace);
    font-size: 11px;
    color: #444;
  }
</style>
