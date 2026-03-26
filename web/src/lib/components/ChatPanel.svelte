<script lang="ts">
	interface ChatMessage {
		role: 'user' | 'assistant';
		content: string;
	}

	interface Props {
		messages: ChatMessage[];
		onSend: (message: string) => void;
		disabled: boolean;
	}

	let { messages, onSend, disabled }: Props = $props();

	let inputValue = $state('');
	let scrollContainer: HTMLDivElement | undefined = $state();

	$effect(() => {
		// Track messages length to auto-scroll
		if (messages.length && scrollContainer) {
			scrollContainer.scrollTop = scrollContainer.scrollHeight;
		}
	});

	function handleSend() {
		const trimmed = inputValue.trim();
		if (!trimmed || disabled) return;
		onSend(trimmed);
		inputValue = '';
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			handleSend();
		}
	}

	/** Detect code blocks (```...```) and inline code (`...`) for font switching */
	function renderContent(text: string): { type: 'text' | 'code' | 'inline-code'; value: string }[] {
		const parts: { type: 'text' | 'code' | 'inline-code'; value: string }[] = [];
		// Split on fenced code blocks first
		const fenced = text.split(/(```[\s\S]*?```)/g);
		for (const segment of fenced) {
			if (segment.startsWith('```') && segment.endsWith('```')) {
				parts.push({ type: 'code', value: segment.slice(3, -3).replace(/^\w*\n/, '') });
			} else {
				// Split on inline code
				const inlineParts = segment.split(/(`[^`]+`)/g);
				for (const ip of inlineParts) {
					if (ip.startsWith('`') && ip.endsWith('`')) {
						parts.push({ type: 'inline-code', value: ip.slice(1, -1) });
					} else if (ip) {
						parts.push({ type: 'text', value: ip });
					}
				}
			}
		}
		return parts;
	}
</script>

<div style="
	display:flex; flex-direction:column; height:100%;
	font-family:var(--sans);
">
	<!-- Messages -->
	<div
		bind:this={scrollContainer}
		role="log"
		aria-live="polite"
		aria-label="Chat messages"
		style="
			flex:1; overflow-y:auto; padding:16px;
			display:flex; flex-direction:column; gap:12px;
		"
	>
		{#if messages.length === 0}
			<div style="
				display:flex; align-items:center; justify-content:center;
				flex:1; padding:40px 20px; text-align:center;
			">
				<p style="
					color:var(--tx-3); font-size:13px; line-height:1.6;
					max-width:320px;
				">Ask about protocol performance, agent behavior, or market dynamics</p>
			</div>
		{:else}
			{#each messages as msg}
				<div style="
					display:flex;
					justify-content:{msg.role === 'user' ? 'flex-end' : 'flex-start'};
				">
					<div style="
						max-width:75%; padding:12px 16px; border-radius:10px;
						background:{msg.role === 'user' ? 'var(--acp)' : 'var(--bg-2)'};
						color:{msg.role === 'user' ? '#fff' : 'var(--tx-1)'};
						font-size:13px; line-height:1.6;
						border-bottom-right-radius:{msg.role === 'user' ? '2px' : '10px'};
						border-bottom-left-radius:{msg.role === 'assistant' ? '2px' : '10px'};
					">
						{#each renderContent(msg.content) as part}
							{#if part.type === 'code'}
								<pre style="
									font-family:'Berkeley Mono', var(--mono), monospace;
									font-size:12px; background:{msg.role === 'user' ? 'rgba(0,0,0,0.2)' : 'var(--bg-0)'};
									padding:10px 12px; border-radius:4px; margin:8px 0;
									overflow-x:auto; white-space:pre-wrap; word-break:break-word;
								">{part.value}</pre>
							{:else if part.type === 'inline-code'}
								<code style="
									font-family:'Berkeley Mono', var(--mono), monospace;
									font-size:12px; padding:2px 5px; border-radius:3px;
									background:{msg.role === 'user' ? 'rgba(0,0,0,0.2)' : 'var(--bg-0)'};
								">{part.value}</code>
							{:else}
								{part.value}
							{/if}
						{/each}
					</div>
				</div>
			{/each}

			{#if disabled}
				<!-- Typing indicator -->
				<div style="display:flex; justify-content:flex-start;">
					<div style="
						padding:12px 16px; border-radius:10px; border-bottom-left-radius:2px;
						background:var(--bg-2); display:flex; gap:5px; align-items:center;
					">
						<span class="dot dot-1" style="
							width:6px; height:6px; border-radius:50%; background:var(--tx-3);
							display:inline-block; animation:typing 1.4s infinite;
						"></span>
						<span class="dot dot-2" style="
							width:6px; height:6px; border-radius:50%; background:var(--tx-3);
							display:inline-block; animation:typing 1.4s infinite 0.2s;
						"></span>
						<span class="dot dot-3" style="
							width:6px; height:6px; border-radius:50%; background:var(--tx-3);
							display:inline-block; animation:typing 1.4s infinite 0.4s;
						"></span>
					</div>
				</div>
			{/if}
		{/if}
	</div>

	<!-- Input -->
	<div style="
		display:flex; gap:8px; padding:12px 16px;
		border-top:1px solid var(--bd); background:var(--bg-1);
	">
		<label for="chat-input" class="sr-only">Type your message</label>
		<input
			id="chat-input"
			type="text"
			bind:value={inputValue}
			onkeydown={handleKeydown}
			placeholder="Ask about the simulation results..."
			{disabled}
			style="
				flex:1; background:var(--bg-2); border:1px solid var(--bd); border-radius:6px;
				padding:10px 14px; color:var(--tx-1); font-family:var(--sans); font-size:13px;
				outline:none; transition:border-color 0.15s;
			"
		/>
		<button
			onclick={handleSend}
			disabled={disabled || !inputValue.trim()}
			style="
				padding:10px 20px; border:none; border-radius:6px;
				background:{disabled || !inputValue.trim() ? 'var(--bg-3)' : 'var(--acp)'};
				color:{disabled || !inputValue.trim() ? 'var(--tx-3)' : '#fff'};
				font-weight:600; font-size:13px; font-family:var(--sans);
				cursor:{disabled || !inputValue.trim() ? 'not-allowed' : 'pointer'};
				transition:background 0.15s;
			"
		>Send</button>
	</div>
</div>

<style>
	@keyframes typing {
		0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
		30% { opacity: 1; transform: translateY(-4px); }
	}
	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}
</style>
