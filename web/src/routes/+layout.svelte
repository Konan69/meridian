<script lang="ts">
	import '../app.css';

	let { children } = $props();
</script>

<svelte:head>
	<title>Meridian</title>
</svelte:head>

<div class="min-h-screen bg-surface-0 text-text-primary">
	<nav class="border-b border-border px-6 py-3 flex items-center justify-between">
		<div class="flex items-center gap-3">
			<span class="text-lg font-semibold tracking-tight">
				<span class="text-blue-500">Meridian</span>
			</span>
			<span class="text-text-muted text-xs font-mono bg-surface-2 px-2 py-0.5 rounded">v0.1.0</span>
		</div>

		<div class="flex items-center gap-6 text-sm text-text-secondary">
			<a href="/" class="hover:text-text-primary transition-colors">Dashboard</a>
			<a href="/sim" class="hover:text-text-primary transition-colors">Simulations</a>
			<a href="/protocols" class="hover:text-text-primary transition-colors">Protocols</a>
		</div>

		<div class="flex items-center gap-2">
			{#each [
				{ name: 'ACP', color: 'bg-protocol-acp' },
				{ name: 'x402', color: 'bg-protocol-x402' },
				{ name: 'AP2', color: 'bg-protocol-ap2' },
				{ name: 'MPP', color: 'bg-protocol-mpp' },
				{ name: 'ATXP', color: 'bg-protocol-atxp' }
			] as protocol}
				<div class="flex items-center gap-1.5 text-xs font-mono">
					<span class="w-2 h-2 rounded-full {protocol.color}"></span>
					<span class="text-text-muted">{protocol.name}</span>
				</div>
			{/each}
		</div>
	</nav>

	<main class="p-6">
		{@render children()}
	</main>
</div>
