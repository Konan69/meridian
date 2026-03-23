<script lang="ts">
	const COLORS: Record<string, string> = {
		acp: 'var(--acp)', ap2: 'var(--ap2)', x402: 'var(--x402)',
		mpp: 'var(--mpp)', atxp: 'var(--atxp)'
	};
	const LABELS: Record<string, string> = {
		acp: 'ACP · Card Rails', ap2: 'AP2 · VDC Multi-Rail', x402: 'x402 · USDC On-Chain',
		mpp: 'MPP · Session Streaming', atxp: 'ATXP · Mandate Engine'
	};

	interface SimEvent { type: string; [k: string]: unknown; }
	interface PM { protocol: string; total_transactions: number; successful_transactions: number; failed_transactions: number; total_volume_cents: number; total_fees_cents: number; avg_settlement_ms: number; micropayment_count: number; }

	let events = $state<SimEvent[]>([]);
	let running = $state(false);
	let complete = $state(false);
	let metrics = $state<PM[]>([]);
	let numAgents = $state(50);
	let numRounds = $state(10);
	let totalTxns = $state(0);
	let totalVol = $state(0);
	let elapsed = $state('');

	function fmt(n: number) { return `$${(n / 100).toFixed(2)}`; }
	function ms(n: number) { return n < 1 ? `${(n * 1000).toFixed(0)}μs` : n < 100 ? `${n.toFixed(2)}ms` : `${n.toFixed(0)}ms`; }

	let purchases = $derived(events.filter(e => e.type === 'purchase'));
	let rounds = $derived(events.filter(e => e.type === 'round_complete'));

	async function run() {
		events = []; running = true; complete = false; metrics = [];
		try {
			const res = await fetch('/api/simulate', {
				method: 'POST', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ agents: numAgents, rounds: numRounds })
			});
			const reader = res.body?.getReader();
			const dec = new TextDecoder();
			let buf = '';
			while (reader) {
				const { done, value } = await reader.read();
				if (done) break;
				buf += dec.decode(value, { stream: true });
				const lines = buf.split('\n');
				buf = lines.pop() || '';
				for (const l of lines) {
					if (!l.trim()) continue;
					try {
						const ev: SimEvent = JSON.parse(l);
						events = [...events, ev];
						if (ev.type === 'simulation_complete') {
							complete = true;
							elapsed = `${ev.duration_seconds}s`;
							totalTxns = ev.total_transactions as number;
							totalVol = ev.total_volume_cents as number;
							metrics = Object.values(ev.protocol_summaries as Record<string, PM>)
								.sort((a, b) => a.avg_settlement_ms - b.avg_settlement_ms);
						}
					} catch {}
				}
			}
		} catch (e) { events = [...events, { type: 'error', message: String(e) }]; }
		running = false;
	}
</script>

<div>
	<!-- Header -->
	<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:24px;">
		<div>
			<h1 style="font-size:22px; font-weight:600; letter-spacing:-0.03em;">Simulation</h1>
			<p style="font-size:13px; color:var(--tx-3); margin-top:4px;">Flat round-robin protocol distribution for fair comparison</p>
		</div>
		<div style="display:flex; align-items:center; gap:14px;">
			<label style="display:flex; flex-direction:column; gap:2px;">
				<span style="font-size:8px; font-weight:600; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em;">Agents</span>
				<input type="number" bind:value={numAgents} min="10" max="1000" style="
					width:60px; background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
					padding:5px 8px; color:var(--tx-1); font-family:var(--mono); font-size:12px;
				" />
			</label>
			<label style="display:flex; flex-direction:column; gap:2px;">
				<span style="font-size:8px; font-weight:600; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.08em;">Rounds</span>
				<input type="number" bind:value={numRounds} min="1" max="100" style="
					width:60px; background:var(--bg-2); border:1px solid var(--bd); border-radius:4px;
					padding:5px 8px; color:var(--tx-1); font-family:var(--mono); font-size:12px;
				" />
			</label>
			<button onclick={run} disabled={running} style="
				padding:8px 20px; border-radius:4px; border:none; font-size:12px; font-weight:600;
				background:{running ? 'var(--bg-3)' : 'var(--acp)'}; color:{running ? 'var(--tx-3)' : '#fff'};
				margin-top:14px; display:flex; align-items:center; gap:6px;
			">
				{#if running}<span class="spin"></span>Running...{:else}Run Simulation{/if}
			</button>
		</div>
	</div>

	{#if complete}
		<!-- Summary -->
		<div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:1px; background:var(--bd); border-radius:6px; overflow:hidden; margin-bottom:20px;">
			{#each [
				{ v: totalTxns, l: 'TRANSACTIONS' },
				{ v: fmt(totalVol), l: 'VOLUME' },
				{ v: elapsed, l: 'DURATION' },
				{ v: numAgents, l: 'AGENTS' },
			] as s}
				<div style="background:var(--bg-1); padding:16px; text-align:center;">
					<div style="font-family:var(--mono); font-size:20px; font-weight:700;">{s.v}</div>
					<div style="font-size:8px; font-weight:600; color:var(--tx-3); text-transform:uppercase; letter-spacing:0.1em; margin-top:4px;">{s.l}</div>
				</div>
			{/each}
		</div>

		<!-- Protocol results table -->
		<div style="background:var(--bg-1); border:1px solid var(--bd); border-radius:6px; padding:20px; margin-bottom:20px;">
			<h2 style="font-size:14px; font-weight:600; margin-bottom:14px;">Protocol Results</h2>
			<table style="width:100%; border-collapse:collapse; font-size:12px;">
				<thead>
					<tr style="border-bottom:1px solid var(--bd); color:var(--tx-3); text-align:left;">
						<th style="padding:8px 12px; font-weight:600;">Protocol</th>
						<th style="padding:8px 8px; text-align:right; font-weight:600;">Txns</th>
						<th style="padding:8px 8px; text-align:right; font-weight:600;">Volume</th>
						<th style="padding:8px 8px; text-align:right; font-weight:600;">Fees</th>
						<th style="padding:8px 8px; text-align:right; font-weight:600;">Fee %</th>
						<th style="padding:8px 8px; text-align:right; font-weight:600;">Avg Exec</th>
						<th style="padding:8px 8px; text-align:right; font-weight:600;">Failed</th>
						<th style="padding:8px 8px; text-align:right; font-weight:600;">Micro</th>
					</tr>
				</thead>
				<tbody>
					{#each metrics as p}
						{@const c = COLORS[p.protocol]}
						{@const v = p.total_volume_cents}
						{@const f = p.total_fees_cents}
						<tr style="border-bottom:1px solid var(--bg-3);">
							<td style="padding:10px 12px;">
								<span style="display:flex; align-items:center; gap:6px;">
									<span style="width:8px; height:8px; border-radius:50%; background:{c};"></span>
									<span style="font-family:var(--mono); font-weight:700; color:{c};">{p.protocol.toUpperCase()}</span>
								</span>
							</td>
							<td style="padding:10px 8px; text-align:right; font-family:var(--mono);">{p.successful_transactions}<span style="color:var(--tx-3);">/{p.total_transactions}</span></td>
							<td style="padding:10px 8px; text-align:right; font-family:var(--mono);">{fmt(v)}</td>
							<td style="padding:10px 8px; text-align:right; font-family:var(--mono);">{fmt(f)}</td>
							<td style="padding:10px 8px; text-align:right; font-family:var(--mono);">{v > 0 ? ((f/v)*100).toFixed(2) : '0'}%</td>
							<td style="padding:10px 8px; text-align:right; font-family:var(--mono);">{ms(p.avg_settlement_ms)}</td>
							<td style="padding:10px 8px; text-align:right; font-family:var(--mono); color:{p.failed_transactions > 0 ? 'var(--ap2)' : 'var(--tx-3)'};">{p.failed_transactions}</td>
							<td style="padding:10px 8px; text-align:right; font-family:var(--mono);">{p.micropayment_count}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	<!-- Live feeds -->
	<div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
		<!-- Rounds -->
		<div style="background:var(--bg-1); border:1px solid var(--bd); border-radius:6px; overflow:hidden;">
			<div style="
				padding:10px 16px; border-bottom:1px solid var(--bd); background:var(--bg-2);
				display:flex; align-items:center; justify-content:space-between;
			">
				<span style="font-size:11px; font-weight:600; color:var(--tx-2); text-transform:uppercase; letter-spacing:0.05em;">Round Progress</span>
				<span style="font-family:var(--mono); font-size:10px; color:var(--tx-3);">{rounds.length}/{numRounds}</span>
			</div>
			<div style="padding:10px 14px; max-height:340px; overflow-y:auto;">
				{#each rounds as rd}
					{@const r = rd as Record<string, unknown>}
					<div style="display:flex; align-items:center; gap:8px; padding:4px 0; font-size:11px;">
						<span style="font-family:var(--mono); color:var(--tx-3); width:28px; text-align:right;">R{r.round}</span>
						<div style="flex:1; height:4px; background:var(--bg-0); border-radius:2px; overflow:hidden;">
							<div style="height:100%; background:var(--acp); border-radius:2px; width:{((r.round as number)/numRounds)*100}%;"></div>
						</div>
						<span style="font-family:var(--mono); font-size:10px; color:var(--tx-2); min-width:130px; text-align:right;">
							{r.success} ok · {r.failed} fail · {fmt(r.volume_cents as number)}
						</span>
					</div>
				{/each}
				{#if running && rounds.length === 0}
					<div style="padding:20px; color:var(--tx-3); font-size:12px; display:flex; align-items:center; gap:8px;">
						<span class="spin-sm"></span> Waiting...
					</div>
				{/if}
			</div>
		</div>

		<!-- Transactions -->
		<div style="background:var(--bg-1); border:1px solid var(--bd); border-radius:6px; overflow:hidden;">
			<div style="
				padding:10px 16px; border-bottom:1px solid var(--bd); background:var(--bg-2);
				display:flex; align-items:center; justify-content:space-between;
			">
				<span style="font-size:11px; font-weight:600; color:var(--tx-2); text-transform:uppercase; letter-spacing:0.05em;">Live Transactions</span>
				<span style="font-family:var(--mono); font-size:10px; color:var(--tx-3);">{purchases.length}</span>
			</div>
			<div style="padding:6px 10px; max-height:340px; overflow-y:auto; font-family:var(--mono); font-size:10px;">
				{#each purchases.slice(-60) as tx}
					{@const t = tx as Record<string, unknown>}
					{@const proto = t.protocol as string}
					<div style="
						display:flex; align-items:center; gap:5px; padding:3px 4px;
						border-bottom:1px solid var(--bg-2);
					">
						<span style="width:5px; height:5px; border-radius:50%; background:{COLORS[proto]}; flex-shrink:0;"></span>
						<span style="color:var(--tx-3); width:22px;">R{t.round}</span>
						<span style="color:var(--tx-2); width:75px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{t.agent}</span>
						<span style="color:var(--tx-3);">→</span>
						<span style="flex:1; color:var(--tx-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{t.product}</span>
						<span style="color:var(--atxp); font-weight:600; white-space:nowrap;">{fmt(t.amount_cents as number)}</span>
						<span style="color:{COLORS[proto]}; font-weight:700; font-size:9px; width:34px; text-align:right;">{proto.toUpperCase()}</span>
					</div>
				{/each}
				{#if running && purchases.length === 0}
					<div style="padding:20px; color:var(--tx-3); font-size:11px; display:flex; align-items:center; gap:8px;">
						<span class="spin-sm"></span> Waiting...
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>

<style>
	.spin, .spin-sm {
		display:inline-block; border:2px solid transparent; border-top-color:currentColor;
		border-radius:50%; animation:sp 0.6s linear infinite;
	}
	.spin { width:14px; height:14px; }
	.spin-sm { width:10px; height:10px; border-width:1.5px; }
	@keyframes sp { to { transform:rotate(360deg); } }

	input:focus { outline:none; border-color:var(--acp); }
</style>
