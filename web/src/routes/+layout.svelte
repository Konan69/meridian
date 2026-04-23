<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	let { children } = $props();

	const NAV = [
		{ href: '/', label: 'Dashboard' },
		{ href: '/sim/new', label: 'Simulation' },
		{ href: '/protocols', label: 'Protocols' },
		{ href: '/funding', label: 'Funding' },
	];

	type CapabilityStatus = {
		protocol: string;
		runtime_ready: boolean;
		integration: string;
		reason: string;
	};

	const COLORS: Record<string, string> = {
		acp: 'var(--acp)',
		x402: 'var(--x402)',
		ap2: 'var(--ap2)',
		mpp: 'var(--mpp)',
		atxp: 'var(--atxp)',
	};

	let protocolStatuses = $state<CapabilityStatus[]>([]);

	async function loadCapabilities() {
		try {
			const res = await fetch('http://localhost:4080/capabilities');
			if (!res.ok) return;
			const data = await res.json();
			if (!Array.isArray(data.protocol_statuses)) return;
			protocolStatuses = data.protocol_statuses.sort((a: CapabilityStatus, b: CapabilityStatus) =>
				a.protocol.localeCompare(b.protocol),
			);
		} catch {
			protocolStatuses = [];
		}
	}

	onMount(() => {
		loadCapabilities();
		const interval = setInterval(loadCapabilities, 10000);
		return () => clearInterval(interval);
	});
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
			<a href="/" aria-label="Meridian Home" style="text-decoration:none; display:flex; align-items:center; gap:8px;">
				<span style="font-family:var(--mono); font-weight:800; font-size:18px; color:var(--acp); letter-spacing:1px;">M</span>
				<span style="font-weight:600; font-size:15px; color:var(--tx-1); letter-spacing:-0.02em;">Meridian</span>
			</a>
			<span style="font-family:var(--mono); font-size:10px; color:var(--tx-3); background:var(--bg-3); padding:2px 6px; border-radius:2px;">v0.1</span>
		</div>

		<nav aria-label="Main navigation" style="
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
					aria-current={page.url.pathname === item.href ? 'page' : undefined}
					style="
						font-size: 12px;
						font-weight: 600;
						color: {page.url.pathname === item.href ? 'var(--tx-1)' : 'var(--tx-3)'};
						text-decoration: none;
						padding: 8px 14px;
						border-radius: 4px;
						background: {page.url.pathname === item.href ? 'var(--bg-4)' : 'transparent'};
						transition: all 0.2s;
					"
				>{item.label}</a>
			{/each}
		</nav>

		<div style="display:flex; align-items:center; gap:14px;" role="status" aria-label="Protocol status indicators">
			{#each protocolStatuses as p}
				<div title={p.reason} style="display:flex; align-items:center; gap:4px; opacity:{p.runtime_ready ? 1 : 0.45};">
					<span style="width:6px; height:6px; border-radius:50%; background:{COLORS[p.protocol] ?? 'var(--tx-3)'};" aria-hidden="true"></span>
					<span style="font-family:var(--mono); font-size:10px; font-weight:600; color:{p.runtime_ready ? 'var(--tx-2)' : 'var(--tx-3)'};">{p.protocol.toUpperCase()}</span>
				</div>
			{/each}
		</div>
	</header>

	<main style="flex:1; padding:28px 32px; max-width:1400px; width:100%; margin:0 auto;">
		{@render children()}
	</main>
</div>
