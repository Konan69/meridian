<script lang="ts">
	import { onMount } from 'svelte';

	type ProtocolStatus = {
		protocol: string;
		runtime_ready: boolean;
		integration: string;
		reason: string;
	};

	type CapabilityResponse = {
		supported_protocols: string[];
		protocol_statuses: ProtocolStatus[];
	};

	type FundingStatus = {
		payerMode: string;
		supportsDirectSettle: boolean;
		reason: string;
		accountAddress?: string;
		network?: string;
		nativeSymbol?: string;
		nativeBalance?: string;
		usdcBalance?: string;
		gasPriceGwei?: string;
		estimatedTransferGasUnits?: number;
		estimatedNativeCost?: string;
		estimatedTransfersRemaining?: number;
		minEstimatedTransfersRequired?: number;
		minUsdcRequired?: string;
		recoveryActions?: string[];
	};

	type HealthResponse = {
		status: string;
		service: string;
		runtimeReadyReason?: string;
		supportsEngineRuntime?: boolean;
		supportsDirectSettle?: boolean;
	};

	const SERVICE_META: Record<string, { label: string; accent: string }> = {
		engine: { label: 'Engine', accent: 'var(--x402)' },
		atxp: { label: 'ATXP', accent: 'var(--atxp)' },
		cdp: { label: 'CDP', accent: 'var(--x402)' },
		stripe: { label: 'MPP/Stripe', accent: 'var(--mpp)' },
		ap2: { label: 'AP2', accent: 'var(--ap2)' }
	};

	let loading = $state(true);
	let engineCaps = $state<CapabilityResponse | null>(null);
	let atxpFunding = $state<FundingStatus | null>(null);
	let atxpMode = $state('current');
	let health = $state<Record<string, HealthResponse | null>>({
		engine: null,
		atxp: null,
		cdp: null,
		stripe: null,
		ap2: null
	});

	function trimAddress(value?: string) {
		if (!value) return '—';
		return `${value.slice(0, 8)}...${value.slice(-6)}`;
	}

	function boolTone(ok?: boolean) {
		return ok ? '#10b981' : '#ef4444';
	}

	async function refresh() {
		try {
			const query = atxpMode === 'current' ? '' : `?mode=${encodeURIComponent(atxpMode)}`;
			const response = await fetch(`/api/funding${query}`);
			if (!response.ok) return;
			const payload = (await response.json()) as {
				engineCaps: CapabilityResponse | null;
				atxpFunding: FundingStatus | null;
				health: Record<string, HealthResponse | null>;
			};

			engineCaps = payload.engineCaps;
			atxpFunding = payload.atxpFunding;
			health = payload.health;
		} catch {
			health = {
				engine: null,
				atxp: null,
				cdp: null,
				stripe: null,
				ap2: null
			};
		}
		loading = false;
	}

	onMount(() => {
		refresh();
		const interval = setInterval(refresh, 5000);
		return () => clearInterval(interval);
	});
</script>

<div style="display:flex; flex-direction:column; gap:20px;">
	<div style="display:flex; justify-content:space-between; gap:16px; align-items:flex-end; flex-wrap:wrap;">
		<div>
			<h1 style="font-size:22px; font-weight:600; letter-spacing:-0.03em;">Funding & Diagnostics</h1>
			<p style="font-size:13px; color:var(--tx-3); margin-top:4px;">
				Live treasury runway, protocol registration, and operator commands.
			</p>
		</div>
		<div style="font-family:var(--mono); font-size:11px; color:var(--tx-3);">
			refresh: 5s
		</div>
	</div>

	{#if loading}
		<div style="padding:72px 0; text-align:center; color:var(--tx-3); font-size:14px;">Loading funding state...</div>
	{:else}
		<div class="service-grid">
			{#each Object.entries(SERVICE_META) as [key, meta]}
				{@const service = health[key]}
				<div class="card">
					<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
						<div style="display:flex; align-items:center; gap:8px;">
							<span style={`width:8px; height:8px; border-radius:50%; background:${boolTone(Boolean(service))};`}></span>
							<span style={`font-family:var(--mono); font-size:12px; font-weight:700; color:${meta.accent};`}>
								{meta.label}
							</span>
						</div>
						<span style="font-size:10px; color:var(--tx-3);">
							{service ? 'up' : 'down'}
						</span>
					</div>
					<div style="font-size:12px; color:var(--tx-2); line-height:1.5;">
						{#if service}
							{service.runtimeReadyReason ?? service.status}
						{:else}
							service unreachable
						{/if}
					</div>
				</div>
			{/each}
		</div>

		<div class="two-col">
			<section class="card">
				<div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:14px;">
					<h2 style="font-size:16px; font-weight:600;">ATXP Treasury</h2>
					<div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap; justify-content:flex-end;">
						<span style="font-family:var(--mono); font-size:10px; color:var(--tx-3);">
							view: {atxpMode === 'current' ? 'current env' : atxpMode}
						</span>
						{#if atxpFunding}
							<span
								style={`font-family:var(--mono); font-size:10px; padding:4px 8px; border-radius:999px; background:${atxpFunding.supportsDirectSettle ? 'rgba(16,185,129,0.12)' : 'rgba(239,68,68,0.12)'}; color:${atxpFunding.supportsDirectSettle ? '#10b981' : '#ef4444'};`}
							>
								{atxpFunding.supportsDirectSettle ? 'runtime-ready' : 'underfunded'}
							</span>
						{/if}
					</div>
				</div>

				{#if atxpFunding}
					<p style="font-size:13px; color:var(--tx-2); margin-bottom:14px; line-height:1.5;">
						{atxpFunding.reason}
					</p>
					<div class="stat-grid">
						<div class="stat">
							<div class="label">Payer Mode</div>
							<div class="value">{atxpFunding.payerMode}</div>
						</div>
						<div class="stat">
							<div class="label">Network</div>
							<div class="value">{atxpFunding.network ?? '—'}</div>
						</div>
						<div class="stat">
							<div class="label">Wallet</div>
							<div class="value">{trimAddress(atxpFunding.accountAddress)}</div>
						</div>
						<div class="stat">
							<div class="label">{atxpFunding.nativeSymbol ?? 'Gas'}</div>
							<div class="value">{atxpFunding.nativeBalance ?? '—'}</div>
						</div>
						<div class="stat">
							<div class="label">USDC</div>
							<div class="value">{atxpFunding.usdcBalance ?? '—'}</div>
						</div>
						<div class="stat">
							<div class="label">Transfers Left</div>
							<div class="value">{atxpFunding.estimatedTransfersRemaining ?? '—'}</div>
						</div>
					</div>

					<div style="margin-top:14px; display:flex; flex-direction:column; gap:8px; font-size:12px; color:var(--tx-2);">
						<div style="display:flex; justify-content:space-between; gap:16px;">
							<span style="color:var(--tx-3);">Gas Price</span>
							<span style="font-family:var(--mono);">{atxpFunding.gasPriceGwei ?? '—'} gwei</span>
						</div>
						<div style="display:flex; justify-content:space-between; gap:16px;">
							<span style="color:var(--tx-3);">Estimated Cost / Transfer</span>
							<span style="font-family:var(--mono);">{atxpFunding.estimatedNativeCost ?? '—'} {atxpFunding.nativeSymbol ?? ''}</span>
						</div>
						<div style="display:flex; justify-content:space-between; gap:16px;">
							<span style="color:var(--tx-3);">Minimum Runway</span>
							<span style="font-family:var(--mono);">
								{atxpFunding.minEstimatedTransfersRequired ?? '—'} tx · {atxpFunding.minUsdcRequired ?? '—'} USDC
							</span>
						</div>
					</div>

					{#if atxpFunding.recoveryActions?.length}
						<div style="margin-top:16px;">
							<div style="font-size:11px; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em; margin-bottom:8px;">
								Recovery
							</div>
							<div style="display:flex; flex-direction:column; gap:8px;">
								{#each atxpFunding.recoveryActions as action}
									<div style="padding:10px 12px; border-radius:6px; background:var(--bg-2); font-size:12px; color:var(--tx-2);">
										{action}
									</div>
								{/each}
							</div>
						</div>
					{/if}
				{:else}
					<div style="font-size:13px; color:var(--tx-3);">ATXP funding endpoint unavailable.</div>
				{/if}
			</section>

			<section class="card">
				<h2 style="font-size:16px; font-weight:600; margin-bottom:14px;">Engine Registration</h2>
				{#if engineCaps}
					<div style="display:flex; flex-wrap:wrap; gap:8px; margin-bottom:14px;">
						{#each engineCaps.supported_protocols as protocol}
							<span style="font-family:var(--mono); font-size:11px; padding:5px 10px; border-radius:999px; background:var(--bg-2); color:var(--tx-2);">
								{protocol}
							</span>
						{/each}
					</div>

					<div style="display:flex; flex-direction:column; gap:10px;">
						{#each engineCaps.protocol_statuses as status}
							<div style="padding:12px; border-radius:8px; background:var(--bg-2);">
								<div style="display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:6px;">
									<span style="font-family:var(--mono); font-size:12px; font-weight:700;">
										{status.protocol.toUpperCase()}
									</span>
									<span
										style={`font-size:10px; color:${status.runtime_ready ? '#10b981' : '#ef4444'}; text-transform:uppercase; letter-spacing:0.08em;`}
									>
										{status.runtime_ready ? 'active' : 'inactive'}
									</span>
								</div>
								<div style="font-size:12px; color:var(--tx-2); line-height:1.5;">
									{status.reason}
								</div>
							</div>
						{/each}
					</div>
				{:else}
					<div style="font-size:13px; color:var(--tx-3);">Engine capabilities endpoint unavailable.</div>
				{/if}
			</section>
		</div>

		<section class="card">
			<h2 style="font-size:16px; font-weight:600; margin-bottom:14px;">Operator Commands</h2>
			<div class="cmd-grid">
				<pre>curl http://localhost:3010/funding</pre>
				<pre>curl 'http://localhost:3010/funding?mode=cdp-base'</pre>
				<pre>curl http://localhost:4080/capabilities</pre>
				<pre>cd services/atxp && pnpm run recover</pre>
				<pre>curl -X POST http://localhost:3030/evm/request-faucet -H 'content-type: application/json' -d '&#123;"address":"0x...","token":"eth"&#125;'</pre>
			</div>
		</section>

		<section class="card">
			<div style="display:flex; justify-content:space-between; gap:16px; align-items:center; flex-wrap:wrap;">
				<div>
					<h2 style="font-size:16px; font-weight:600;">ATXP Mode Probe</h2>
					<p style="font-size:12px; color:var(--tx-3); margin-top:4px;">
						Inspect an alternate payer mode without editing <code>.env</code>.
					</p>
				</div>
				<label style="display:flex; align-items:center; gap:8px; font-size:12px; color:var(--tx-2);">
					<span>Mode</span>
					<select
						bind:value={atxpMode}
						onchange={() => {
							loading = true;
							refresh();
						}}
						style="background:var(--bg-2); color:var(--tx-1); border:1px solid var(--bd); border-radius:6px; padding:8px 10px;"
					>
						<option value="current">current env</option>
						<option value="polygon">polygon</option>
						<option value="cdp-base">cdp-base</option>
						<option value="base">base</option>
						<option value="atxp">atxp</option>
					</select>
				</label>
			</div>
		</section>
	{/if}
</div>

<style>
	.card {
		background: var(--bg-1);
		border: 1px solid var(--bd);
		border-radius: 10px;
		padding: 18px;
	}

	.service-grid {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: 10px;
	}

	.two-col {
		display: grid;
		grid-template-columns: 1.2fr 1fr;
		gap: 14px;
	}

	.stat-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 10px;
	}

	.stat {
		background: var(--bg-2);
		border-radius: 8px;
		padding: 12px;
	}

	.label {
		font-size: 10px;
		color: var(--tx-3);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		margin-bottom: 6px;
	}

	.value {
		font-family: var(--mono);
		font-size: 14px;
		font-weight: 600;
		color: var(--tx-1);
	}

	.cmd-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 10px;
	}

	pre {
		margin: 0;
		padding: 12px;
		border-radius: 8px;
		background: var(--bg-2);
		color: var(--tx-2);
		font-size: 12px;
		font-family: var(--mono);
		overflow: auto;
	}

	@media (max-width: 1100px) {
		.service-grid {
			grid-template-columns: repeat(3, 1fr);
		}

		.two-col {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 760px) {
		.service-grid,
		.stat-grid,
		.cmd-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
