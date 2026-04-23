<script>
  import { getProtocolColor, getProtocolDisplayLabel } from '$lib/constants';
  /** @type {{ protocol: string }} */
  let { protocol } = $props();

  let label = $derived(getProtocolDisplayLabel(protocol));
  let dotColor = $derived(getProtocolColor(protocol ?? ''));
</script>

<span
  class="protocol-badge"
  style:--dot-color={dotColor}
  aria-label="Protocol: {label}"
>
  <span class="dot" aria-hidden="true"></span>
  {label}
</span>

<style>
  .protocol-badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 2px 8px;
    border-radius: 9999px;
    font-family: var(--mono, monospace);
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.05em;
    color: var(--tx-2, #aaa);
    background: var(--bg-2, #1a1a1a);
    border: 1px solid var(--bd, #333);
    white-space: nowrap;
    user-select: none;
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--dot-color);
    flex-shrink: 0;
  }
</style>
