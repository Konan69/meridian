/**
 * Demo data generator for the commerce knowledge graph.
 * Produces sample buyers, merchants, products, brands, and edges between them.
 */

export interface GraphNode {
	id: string;
	name: string;
	type: 'Buyer' | 'Merchant' | 'Product' | 'Brand' | 'Transaction';
	color?: string;
	properties?: Record<string, string>;
}

export interface GraphEdge {
	source: string;
	target: string;
	label?: string;
}

export interface GraphData {
	nodes: GraphNode[];
	edges: GraphEdge[];
}

const TYPE_COLORS: Record<string, string> = {
	Buyer: '#3b82f6',
	Merchant: '#10b981',
	Product: '#f59e0b',
	Brand: '#8b5cf6',
	Transaction: '#ef4444'
};

export function generateDemoGraph(): GraphData {
	const nodes: GraphNode[] = [
		// Buyers
		{ id: 'b1', name: 'Agent Alice', type: 'Buyer', properties: { protocol: 'ACP', budget: '$2,400' } },
		{ id: 'b2', name: 'Agent Bob', type: 'Buyer', properties: { protocol: 'x402', budget: '$1,800' } },
		{ id: 'b3', name: 'Agent Carol', type: 'Buyer', properties: { protocol: 'AP2', budget: '$3,100' } },
		{ id: 'b4', name: 'Agent Dave', type: 'Buyer', properties: { protocol: 'MPP', budget: '$950' } },
		{ id: 'b5', name: 'Agent Eve', type: 'Buyer', properties: { protocol: 'ATXP', budget: '$4,200' } },

		// Merchants
		{ id: 'm1', name: 'NovaParts Co', type: 'Merchant', properties: { category: 'Electronics', rating: '4.8' } },
		{ id: 'm2', name: 'GreenLeaf Market', type: 'Merchant', properties: { category: 'Organic Goods', rating: '4.5' } },
		{ id: 'm3', name: 'ByteForge Labs', type: 'Merchant', properties: { category: 'Software', rating: '4.9' } },

		// Products
		{ id: 'p1', name: 'GPU Cluster v4', type: 'Product', properties: { price: '$899', sku: 'NP-GPU-04' } },
		{ id: 'p2', name: 'Neural Coprocessor', type: 'Product', properties: { price: '$1,249', sku: 'NP-NCP-01' } },
		{ id: 'p3', name: 'Organic Dataset Pack', type: 'Product', properties: { price: '$45', sku: 'GL-ODP-12' } },
		{ id: 'p4', name: 'Inference API Key', type: 'Product', properties: { price: '$120/mo', sku: 'BF-IAK-01' } },
		{ id: 'p5', name: 'Edge TPU Module', type: 'Product', properties: { price: '$349', sku: 'NP-TPU-02' } },
		{ id: 'p6', name: 'Training Pipeline SaaS', type: 'Product', properties: { price: '$299/mo', sku: 'BF-TPS-03' } },

		// Brands
		{ id: 'br1', name: 'NovaTech', type: 'Brand', properties: { sector: 'Hardware' } },
		{ id: 'br2', name: 'ByteForge', type: 'Brand', properties: { sector: 'Cloud AI' } },

		// Transactions
		{ id: 't1', name: 'TXN-0x7a3f', type: 'Transaction', properties: { amount: '$899', status: 'settled', protocol: 'ACP' } },
		{ id: 't2', name: 'TXN-0x9b1c', type: 'Transaction', properties: { amount: '$120', status: 'pending', protocol: 'x402' } },
		{ id: 't3', name: 'TXN-0x4e8d', type: 'Transaction', properties: { amount: '$349', status: 'settled', protocol: 'AP2' } }
	];

	// Assign colors based on type
	for (const node of nodes) {
		node.color = TYPE_COLORS[node.type];
	}

	const edges: GraphEdge[] = [
		// Merchant -> Product (sells)
		{ source: 'm1', target: 'p1', label: 'sells' },
		{ source: 'm1', target: 'p2', label: 'sells' },
		{ source: 'm1', target: 'p5', label: 'sells' },
		{ source: 'm2', target: 'p3', label: 'sells' },
		{ source: 'm3', target: 'p4', label: 'sells' },
		{ source: 'm3', target: 'p6', label: 'sells' },

		// Brand -> Product (manufactures)
		{ source: 'br1', target: 'p1', label: 'manufactures' },
		{ source: 'br1', target: 'p2', label: 'manufactures' },
		{ source: 'br1', target: 'p5', label: 'manufactures' },
		{ source: 'br2', target: 'p4', label: 'manufactures' },
		{ source: 'br2', target: 'p6', label: 'manufactures' },

		// Buyer -> Transaction (initiated)
		{ source: 'b1', target: 't1', label: 'initiated' },
		{ source: 'b2', target: 't2', label: 'initiated' },
		{ source: 'b3', target: 't3', label: 'initiated' },

		// Transaction -> Product (for)
		{ source: 't1', target: 'p1', label: 'for' },
		{ source: 't2', target: 'p4', label: 'for' },
		{ source: 't3', target: 'p5', label: 'for' },

		// Buyer -> Product (reviewed / wishlisted)
		{ source: 'b4', target: 'p3', label: 'reviewed' },
		{ source: 'b5', target: 'p6', label: 'wishlisted' },
		{ source: 'b1', target: 'p2', label: 'wishlisted' },
		{ source: 'b3', target: 'p1', label: 'reviewed' },

		// Buyer -> Merchant (trusts)
		{ source: 'b5', target: 'm3', label: 'trusts' },
		{ source: 'b2', target: 'm1', label: 'trusts' }
	];

	return { nodes, edges };
}
