import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

export const POST: RequestHandler = async ({ request }) => {
	const { messages, context } = await request.json();

	const apiKey = env.OPENCODE_API_KEY;
	if (!apiKey) {
		return new Response(
			JSON.stringify({ error: 'OPENCODE_API_KEY not configured' }),
			{ status: 500, headers: { 'Content-Type': 'application/json' } },
		);
	}

	const systemMessage = {
		role: 'system',
		content: `You are Meridian, an expert analyst for agentic commerce simulations. You analyze protocol performance data across ACP, AP2, x402, MPP, and ATXP payment protocols. Be precise with numbers, use data from the simulation context, and highlight surprising patterns. Keep responses concise and data-driven.\n\nSimulation context:\n${context || 'No context provided.'}`,
	};

	const res = await fetch('https://opencode.ai/zen/v1/chat/completions', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			'Authorization': `Bearer ${apiKey}`,
		},
		body: JSON.stringify({
			model: 'minimax-m2.5-free',
			messages: [systemMessage, ...messages],
			stream: true,
		}),
	});

	if (!res.ok) {
		const text = await res.text();
		return new Response(
			JSON.stringify({ error: `Upstream error: ${res.status}`, detail: text }),
			{ status: res.status, headers: { 'Content-Type': 'application/json' } },
		);
	}

	// Stream the SSE response through to the client
	const upstream = res.body;
	if (!upstream) {
		return new Response(
			JSON.stringify({ error: 'No response body from upstream' }),
			{ status: 502, headers: { 'Content-Type': 'application/json' } },
		);
	}

	const transform = new TransformStream({
		transform(chunk, controller) {
			controller.enqueue(chunk);
		},
	});

	upstream.pipeTo(transform.writable);

	return new Response(transform.readable, {
		headers: {
			'Content-Type': 'text/event-stream',
			'Cache-Control': 'no-cache',
			'Connection': 'keep-alive',
		},
	});
};
