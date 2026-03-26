<script lang="ts">
	import {
		forceSimulation,
		forceLink,
		forceManyBody,
		forceCenter,
		forceCollide,
		type SimulationNodeDatum,
		type SimulationLinkDatum
	} from 'd3-force';
	import { zoom as d3Zoom, zoomIdentity, type ZoomBehavior } from 'd3-zoom';
	import { select } from 'd3-selection';
	import type { GraphNode, GraphEdge } from './graphDemo';
	import { TYPE_COLORS, getEntityColor } from '$lib/constants';

	/* ── Types ── */

	interface SimNode extends SimulationNodeDatum {
		id: string;
		name: string;
		type: string;
		color: string;
		properties?: Record<string, string>;
	}

	interface SimLink extends SimulationLinkDatum<SimNode> {
		label?: string;
	}

	interface SelectedDetail {
		node: SimNode;
	}

	/* ── Constants ── */

	const ENTITY_TYPES = Object.keys(TYPE_COLORS);

	const NODE_RADIUS = 20;

	/* ── Props ── */

	interface Props {
		nodes: GraphNode[];
		edges: GraphEdge[];
	}

	let { nodes, edges }: Props = $props();

	/* ── State ── */

	let simNodes: SimNode[] = $state([]);
	let simLinks: SimLink[] = $state([]);
	let selected: SelectedDetail | null = $state(null);
	let transform = $state({ x: 0, y: 0, k: 1 });
	let tick = $state(0); // force re-render on sim tick

	let svgEl: SVGSVGElement | undefined = $state(undefined);
	let containerEl: HTMLDivElement | undefined = $state(undefined);
	let simulation: ReturnType<typeof forceSimulation<SimNode>> | null = null;
	let zoomBehavior: ZoomBehavior<SVGSVGElement, unknown> | null = null;

	/* ── Simulation setup ── */

	function buildSimulation(rawNodes: GraphNode[], rawEdges: GraphEdge[]) {
		// Stop previous
		if (simulation) simulation.stop();

		// Deep-copy into SimNode[]
		const nodeMap = new Map<string, SimNode>();
		const sNodes: SimNode[] = rawNodes.map((n) => {
			const sn: SimNode = {
				id: n.id,
				name: n.name,
				type: n.type,
				color: n.color ?? getEntityColor(n.type),
				properties: n.properties
			};
			nodeMap.set(n.id, sn);
			return sn;
		});

		const sLinks: SimLink[] = rawEdges
			.filter((e) => nodeMap.has(e.source) && nodeMap.has(e.target))
			.map((e) => ({
				source: e.source,
				target: e.target,
				label: e.label
			}));

		simNodes = sNodes;
		simLinks = sLinks;

		simulation = forceSimulation<SimNode>(sNodes)
			.force(
				'link',
				forceLink<SimNode, SimLink>(sLinks)
					.id((d) => d.id)
					.distance(150)
			)
			.force('charge', forceManyBody().strength(-400))
			.force('center', forceCenter(0, 0).strength(0.04))
			.force('collision', forceCollide(50))
			.on('tick', () => {
				tick++;
			});
	}

	/* ── Zoom setup ── */

	function setupZoom() {
		if (!svgEl) return;

		const svg = select<SVGSVGElement, unknown>(svgEl);

		// Remove any prior zoom
		svg.on('.zoom', null);

		zoomBehavior = d3Zoom<SVGSVGElement, unknown>()
			.scaleExtent([0.1, 6])
			.on('zoom', (event) => {
				transform = { x: event.transform.x, y: event.transform.y, k: event.transform.k };
			});

		svg.call(zoomBehavior);

		// Center the view
		if (containerEl) {
			const rect = containerEl.getBoundingClientRect();
			const initial = zoomIdentity.translate(rect.width / 2, rect.height / 2);
			svg.call(zoomBehavior.transform, initial);
		}
	}

	/* ── Reactivity ── */

	$effect(() => {
		if (nodes && edges) {
			buildSimulation(nodes, edges);
		}
	});

	$effect(() => {
		if (svgEl) {
			setupZoom();
		}
	});

	/* ── Interaction ── */

	let connectedEdges = $derived.by(() => {
		const sel = selected;
		if (!sel) return [];
		return edges.filter((e) => e.source === sel.node.id || e.target === sel.node.id);
	});

	function handleNodeClick(node: SimNode) {
		selected = { node };
	}

	function handleNodeKeydown(e: KeyboardEvent, node: SimNode) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			selected = { node };
		}
	}

	function closeDetail() {
		selected = null;
	}

	/* ── Helpers ── */

	function linkX1(link: SimLink): number {
		void tick;
		const s = link.source as SimNode;
		return s.x ?? 0;
	}
	function linkY1(link: SimLink): number {
		void tick;
		const s = link.source as SimNode;
		return s.y ?? 0;
	}
	function linkX2(link: SimLink): number {
		void tick;
		const t = link.target as SimNode;
		return t.x ?? 0;
	}
	function linkY2(link: SimLink): number {
		void tick;
		const t = link.target as SimNode;
		return t.y ?? 0;
	}
	function linkMidX(link: SimLink): number {
		return (linkX1(link) + linkX2(link)) / 2;
	}
	function linkMidY(link: SimLink): number {
		return (linkY1(link) + linkY2(link)) / 2;
	}
	function nodeX(node: SimNode): number {
		void tick;
		return node.x ?? 0;
	}
	function nodeY(node: SimNode): number {
		void tick;
		return node.y ?? 0;
	}
</script>

<div
	bind:this={containerEl}
	style="
		position: relative;
		width: 100%;
		height: 100%;
		background-color: var(--bg-0, #09090b);
		background-image: radial-gradient(var(--bd, #27272a) 1px, transparent 1px);
		background-size: 24px 24px;
		overflow: hidden;
		border-radius: 12px;
		font-family: var(--sans, 'Space Grotesk', sans-serif);
	"
>
	<!-- SVG graph -->
	<svg
		bind:this={svgEl}
		style="
			width: 100%;
			height: 100%;
			display: block;
			cursor: grab;
		"
	>
		<g transform="translate({transform.x}, {transform.y}) scale({transform.k})">
			<!-- Edges -->
			{#each simLinks as link (((link.source as SimNode).id ?? '') + '-' + ((link.target as SimNode).id ?? '') + '-' + (link.label ?? ''))}
				<line
					x1={linkX1(link)}
					y1={linkY1(link)}
					x2={linkX2(link)}
					y2={linkY2(link)}
					style="stroke: var(--bd, #27272a); stroke-width: 1.5; stroke-opacity: 0.6;"
				/>
				{#if link.label}
					<text
						x={linkMidX(link)}
						y={linkMidY(link) - 6}
						style="
							fill: var(--tx-3, #52525b);
							font-size: 10px;
							font-family: var(--mono, 'Berkeley Mono', monospace);
							text-anchor: middle;
							pointer-events: none;
							user-select: none;
						"
					>
						{link.label}
					</text>
				{/if}
			{/each}

			<!-- Nodes -->
			{#each simNodes as node (node.id)}
				<g
					transform="translate({nodeX(node)}, {nodeY(node)})"
					style="cursor: pointer;"
					role="button"
					tabindex="0"
					aria-label="{node.type}: {node.name}"
					onclick={() => handleNodeClick(node)}
					onkeydown={(e) => handleNodeKeydown(e, node)}
				>
					<!-- Outer glow for selected -->
					{#if selected?.node.id === node.id}
						<circle
							r={NODE_RADIUS + 6}
							style="fill: none; stroke: {node.color}; stroke-width: 2; stroke-opacity: 0.4;"
						/>
					{/if}
					<!-- Node circle -->
					<circle
						r={NODE_RADIUS}
						style="
							fill: {node.color};
							fill-opacity: 0.15;
							stroke: {node.color};
							stroke-width: 2;
						"
					/>
					<!-- Inner dot -->
					<circle r={5} style="fill: {node.color};" />
					<!-- Label -->
					<text
						y={NODE_RADIUS + 16}
						style="
							fill: var(--tx-2, #a1a1aa);
							font-size: 11px;
							font-family: var(--mono, 'Berkeley Mono', monospace);
							text-anchor: middle;
							pointer-events: none;
							user-select: none;
						"
					>
						{node.name}
					</text>
				</g>
			{/each}
		</g>
	</svg>

	<!-- Legend -->
	<div
		style="
			position: absolute;
			bottom: 16px;
			left: 16px;
			display: flex;
			flex-direction: column;
			gap: 6px;
			padding: 12px 14px;
			background: var(--bg-1, #18181b);
			border: 1px solid var(--bd, #27272a);
			border-radius: 8px;
			pointer-events: none;
			user-select: none;
		"
	>
		<span
			style="
				font-size: 10px;
				font-family: var(--sans, 'Space Grotesk', sans-serif);
				color: var(--tx-3, #52525b);
				text-transform: uppercase;
				letter-spacing: 0.08em;
				margin-bottom: 2px;
			"
		>
			Entity Types
		</span>
		{#each ENTITY_TYPES as entityType}
			<div style="display: flex; align-items: center; gap: 8px;">
				<span
					style="
						width: 10px;
						height: 10px;
						border-radius: 50%;
						background: {getEntityColor(entityType)};
						flex-shrink: 0;
					"
				></span>
				<span
					style="
						font-size: 11px;
						font-family: var(--mono, 'Berkeley Mono', monospace);
						color: var(--tx-2, #a1a1aa);
					"
				>
					{entityType}
				</span>
			</div>
		{/each}
	</div>

	<!-- Detail panel -->
	{#if selected}
		<div
			style="
				position: absolute;
				top: 16px;
				right: 16px;
				width: 280px;
				max-height: calc(100% - 32px);
				overflow-y: auto;
				background: var(--bg-1, #18181b);
				border: 1px solid var(--bd, #27272a);
				border-radius: 10px;
				padding: 0;
				font-family: var(--sans, 'Space Grotesk', sans-serif);
			"
		>
			<!-- Header -->
			<div
				style="
					display: flex;
					align-items: center;
					justify-content: space-between;
					padding: 14px 16px;
					border-bottom: 1px solid var(--bd, #27272a);
				"
			>
				<div style="display: flex; align-items: center; gap: 8px;">
					<span
						style="
							font-size: 14px;
							font-weight: 600;
							color: var(--tx-1, #fafafa);
							font-family: var(--sans, 'Space Grotesk', sans-serif);
						"
					>
						{selected.node.name}
					</span>
					<span
						style="
							font-size: 10px;
							padding: 2px 8px;
							border-radius: 9999px;
							background: {selected.node.color}22;
							color: {selected.node.color};
							font-family: var(--mono, 'Berkeley Mono', monospace);
						"
					>
						{selected.node.type}
					</span>
				</div>
				<button
					onclick={closeDetail}
					aria-label="Close detail panel"
					style="
						background: none;
						border: none;
						color: var(--tx-3, #52525b);
						font-size: 18px;
						cursor: pointer;
						padding: 8px 12px;
						line-height: 1;
					"
				>
					&times;
				</button>
			</div>

			<!-- Body -->
			<div style="padding: 14px 16px; display: flex; flex-direction: column; gap: 10px;">
				<!-- ID -->
				<div style="display: flex; justify-content: space-between; align-items: baseline;">
					<span
						style="
							font-size: 11px;
							color: var(--tx-3, #52525b);
							font-family: var(--mono, 'Berkeley Mono', monospace);
						"
					>
						id
					</span>
					<span
						style="
							font-size: 12px;
							color: var(--tx-2, #a1a1aa);
							font-family: var(--mono, 'Berkeley Mono', monospace);
						"
					>
						{selected.node.id}
					</span>
				</div>

				<!-- Properties -->
				{#if selected.node.properties}
					<div
						style="
							border-top: 1px solid var(--bd, #27272a);
							padding-top: 10px;
							margin-top: 2px;
						"
					>
						<span
							style="
								font-size: 10px;
								color: var(--tx-3, #52525b);
								text-transform: uppercase;
								letter-spacing: 0.08em;
								font-family: var(--sans, 'Space Grotesk', sans-serif);
							"
						>
							Properties
						</span>
						<div
							style="
								display: flex;
								flex-direction: column;
								gap: 6px;
								margin-top: 8px;
							"
						>
							{#each Object.entries(selected.node.properties) as [key, value]}
								<div style="display: flex; justify-content: space-between; align-items: baseline;">
									<span
										style="
											font-size: 11px;
											color: var(--tx-3, #52525b);
											font-family: var(--mono, 'Berkeley Mono', monospace);
										"
									>
										{key}
									</span>
									<span
										style="
											font-size: 12px;
											color: var(--tx-1, #fafafa);
											font-family: var(--mono, 'Berkeley Mono', monospace);
										"
									>
										{value}
									</span>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Connected edges -->
				{#if connectedEdges.length > 0}
					<div
						style="
							border-top: 1px solid var(--bd, #27272a);
							padding-top: 10px;
							margin-top: 2px;
						"
					>
						<span
							style="
								font-size: 10px;
								color: var(--tx-3, #52525b);
								text-transform: uppercase;
								letter-spacing: 0.08em;
								font-family: var(--sans, 'Space Grotesk', sans-serif);
							"
						>
							Connections ({connectedEdges.length})
						</span>
						<div
							style="
								display: flex;
								flex-direction: column;
								gap: 4px;
								margin-top: 8px;
							"
						>
							{#each connectedEdges as edge}
								{@const isSource = edge.source === selected?.node.id}
								<div
									style="
										font-size: 11px;
										font-family: var(--mono, 'Berkeley Mono', monospace);
										color: var(--tx-2, #a1a1aa);
										display: flex;
										gap: 4px;
										align-items: baseline;
									"
								>
									<span style="color: var(--tx-3, #52525b);">
										{isSource ? '\u2192' : '\u2190'}
									</span>
									<span style="color: {getEntityColor(nodes.find((n) => n.id === (isSource ? edge.target : edge.source))?.type ?? '')};">
										{nodes.find((n) => n.id === (isSource ? edge.target : edge.source))?.name ?? '?'}
									</span>
									{#if edge.label}
										<span style="color: var(--tx-3, #52525b); font-size: 10px;">
											({edge.label})
										</span>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
