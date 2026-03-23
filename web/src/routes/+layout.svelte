<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';

	let { children } = $props();

	const NAV_ITEMS = [
		{ href: '/', label: 'Dashboard' },
		{ href: '/sim', label: 'Simulation' },
		{ href: '/protocols', label: 'Protocols' },
	];

	const PROTOCOLS = [
		{ name: 'ACP', color: '#3b82f6' },
		{ name: 'x402', color: '#10b981' },
		{ name: 'AP2', color: '#ef4444' },
		{ name: 'MPP', color: '#8b5cf6' },
		{ name: 'ATXP', color: '#f59e0b' },
	];
</script>

<svelte:head>
	<title>Meridian</title>
</svelte:head>

<div class="app-shell">
	<!-- MiroFish-style header: 60px height, black bg, clean type -->
	<header class="app-header">
		<div class="header-left">
			<a href="/" class="brand">
				<span class="brand-mark">M</span>
				<span class="brand-name">Meridian</span>
			</a>
			<span class="version-badge">v0.1.0</span>
		</div>

		<nav class="header-center">
			{#each NAV_ITEMS as item}
				<a
					href={item.href}
					class="nav-link"
					class:active={page.url.pathname === item.href}
				>
					{item.label}
				</a>
			{/each}
		</nav>

		<div class="header-right">
			{#each PROTOCOLS as proto}
				<div class="proto-indicator">
					<span class="proto-dot" style="background: {proto.color}"></span>
					<span class="proto-label">{proto.name}</span>
				</div>
			{/each}
		</div>
	</header>

	<main class="app-main">
		{@render children()}
	</main>
</div>

<style>
	.app-shell {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
	}

	/* Header — MiroFish pattern: 60px, clean, monochrome */
	.app-header {
		height: 60px;
		padding: 0 24px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		border-bottom: 1px solid var(--color-border);
		background: var(--color-surface-1);
		z-index: 100;
		flex-shrink: 0;
	}

	.header-left {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.brand {
		display: flex;
		align-items: center;
		gap: 8px;
		text-decoration: none;
		color: var(--color-text-primary);
	}

	.brand-mark {
		font-family: var(--font-mono);
		font-weight: 800;
		font-size: 18px;
		letter-spacing: 1px;
		color: var(--color-protocol-acp);
	}

	.brand-name {
		font-family: var(--font-sans);
		font-weight: 600;
		font-size: 16px;
		letter-spacing: -0.02em;
	}

	.version-badge {
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 500;
		color: var(--color-text-muted);
		background: var(--color-surface-3);
		padding: 2px 6px;
		border-radius: 2px;
		letter-spacing: 0.03em;
	}

	/* Center nav — MiroFish uses absolute centering */
	.header-center {
		position: absolute;
		left: 50%;
		transform: translateX(-50%);
		display: flex;
		gap: 4px;
		background: var(--color-surface-2);
		padding: 4px;
		border-radius: 6px;
	}

	.nav-link {
		font-size: 12px;
		font-weight: 600;
		color: var(--color-text-muted);
		text-decoration: none;
		padding: 6px 16px;
		border-radius: 4px;
		transition: all 0.2s;
	}

	.nav-link:hover {
		color: var(--color-text-secondary);
	}

	.nav-link.active {
		color: var(--color-text-primary);
		background: var(--color-surface-4);
		box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
	}

	/* Protocol indicators */
	.header-right {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.proto-indicator {
		display: flex;
		align-items: center;
		gap: 5px;
	}

	.proto-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
	}

	.proto-label {
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 600;
		color: var(--color-text-muted);
		letter-spacing: 0.03em;
	}

	/* Main content */
	.app-main {
		flex: 1;
		padding: 24px;
		max-width: 1400px;
		width: 100%;
		margin: 0 auto;
	}
</style>
