<script lang="ts">
	import type { SimStep } from '$lib/stores/simulation.svelte';

	const { currentStep, onStepClick }: {
		currentStep: SimStep;
		onStepClick: (step: SimStep) => void;
	} = $props();

	const STEPS: { key: SimStep; num: string; label: string }[] = [
		{ key: 'seed', num: '01', label: 'Seed Data' },
		{ key: 'graph', num: '02', label: 'Knowledge Graph' },
		{ key: 'agents', num: '03', label: 'Agent Setup' },
		{ key: 'simulate', num: '04', label: 'Simulation' },
		{ key: 'report', num: '05', label: 'Report' },
		{ key: 'chat', num: '06', label: 'Interact' },
	];

	const stepOrder = STEPS.map(s => s.key);

	function status(key: SimStep): 'active' | 'completed' | 'pending' {
		const ci = stepOrder.indexOf(currentStep);
		const si = stepOrder.indexOf(key);
		if (si === ci) return 'active';
		if (si < ci) return 'completed';
		return 'pending';
	}

	function canNavigateTo(key: SimStep): boolean {
		const ci = stepOrder.indexOf(currentStep);
		const si = stepOrder.indexOf(key);
		// Can only go to current step or completed (previous) steps
		return si <= ci;
	}
</script>

<div style="display:flex; gap:2px; align-items:center;" role="navigation" aria-label="Simulation steps">
	{#each STEPS as step, i}
		{@const s = status(step.key)}
		{@const clickable = canNavigateTo(step.key)}
		<button
			onclick={() => clickable && onStepClick(step.key)}
			disabled={!clickable}
			aria-current={s === 'active' ? 'step' : undefined}
			style="
				display:flex; align-items:center; gap:8px;
				padding:10px 16px;
				background:{s === 'active' ? 'var(--bg-3)' : 'transparent'};
				border:none;
				border-radius:4px;
				cursor:{clickable ? 'pointer' : 'default'};
				opacity:{clickable ? '1' : '0.4'};
				transition:all 0.2s;
			"
		>
			<span style="
				font-family:var(--mono); font-size:10px; font-weight:700;
				color:{s === 'active' ? 'var(--acp)' : s === 'completed' ? 'var(--x402)' : 'var(--tx-3)'};
			">{step.num}</span>
			<span style="
				font-size:12px; font-weight:600;
				color:{s === 'active' ? 'var(--tx-1)' : s === 'completed' ? 'var(--tx-2)' : 'var(--tx-3)'};
			">{step.label}</span>
			{#if s === 'completed'}
				<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="var(--x402)" stroke-width="3" aria-hidden="true">
					<polyline points="20 6 9 17 4 12"></polyline>
				</svg>
			{/if}
		</button>
		{#if i < STEPS.length - 1}
			<div style="width:1px; height:14px; background:var(--bg-4);"></div>
		{/if}
	{/each}
</div>
