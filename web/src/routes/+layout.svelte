<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';
	let { children } = $props();

	const NAV = [
		{ href: '/', label: 'Dashboard' },
		{ href: '/sim/new', label: 'Simulation' },
		{ href: '/protocols', label: 'Protocols' },
	];

	const PROTOS = [
		{ n: 'ACP', c: 'var(--acp)' },
		{ n: 'x402', c: 'var(--x402)' },
		{ n: 'AP2', c: 'var(--ap2)' },
		{ n: 'MPP', c: 'var(--mpp)' },
		{ n: 'ATXP', c: 'var(--atxp)' },
	];
</script>

<svelte:head><title>Meridian</title></svelte:head>

<div style="min-height:100vh; display:flex; flex-direction:column;">
	<header style="
		height: 56px;
		padding: 0 24px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		border-bottom: 1px solid var(--bd);
		background: var(--bg-1);
		flex-shrink: 0;
		position: relative;
	">
		<div style="display:flex; align-items:center; gap:10px;">
			<a href="/" style="text-decoration:none; display:flex; align-items:center; gap:8px;">
				<span style="font-family:var(--mono); font-weight:800; font-size:18px; color:var(--acp); letter-spacing:1px;">M</span>
				<span style="font-weight:600; font-size:15px; color:var(--tx-1); letter-spacing:-0.02em;">Meridian</span>
			</a>
			<span style="font-family:var(--mono); font-size:10px; color:var(--tx-3); background:var(--bg-3); padding:2px 6px; border-radius:2px;">v0.1</span>
		</div>

		<nav style="
			position: absolute;
			left: 50%;
			transform: translateX(-50%);
			display: flex;
			gap: 2px;
			background: var(--bg-2);
			padding: 3px;
			border-radius: 6px;
		">
			{#each NAV as item}
				<a
					href={item.href}
					style="
						font-size: 12px;
						font-weight: 600;
						color: {page.url.pathname === item.href ? 'var(--tx-1)' : 'var(--tx-3)'};
						text-decoration: none;
						padding: 5px 14px;
						border-radius: 4px;
						background: {page.url.pathname === item.href ? 'var(--bg-4)' : 'transparent'};
						transition: all 0.2s;
					"
				>{item.label}</a>
			{/each}
		</nav>

		<div style="display:flex; align-items:center; gap:14px;">
			{#each PROTOS as p}
				<div style="display:flex; align-items:center; gap:4px;">
					<span style="width:6px; height:6px; border-radius:50%; background:{p.c};"></span>
					<span style="font-family:var(--mono); font-size:10px; font-weight:600; color:var(--tx-3);">{p.n}</span>
				</div>
			{/each}
		</div>
	</header>

	<main style="flex:1; padding:28px 32px; max-width:1400px; width:100%; margin:0 auto;">
		{@render children()}
	</main>
</div>
