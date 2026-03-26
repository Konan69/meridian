import { createOpenAICompatible } from '@ai-sdk/openai-compatible';
import { streamText } from 'ai';
import type { RequestHandler } from './$types';
import { env } from '$env/dynamic/private';

const opencode = createOpenAICompatible({
	name: 'opencode-zen',
	baseURL: 'https://opencode.ai/zen/v1',
	headers: () => ({
		Authorization: `Bearer ${env.OPENCODE_API_KEY ?? ''}`,
	}),
});

export const POST: RequestHandler = async ({ request }) => {
	const { messages, context } = await request.json();

	if (!env.OPENCODE_API_KEY) {
		return new Response(
			JSON.stringify({ error: 'OPENCODE_API_KEY not configured' }),
			{ status: 500, headers: { 'Content-Type': 'application/json' } },
		);
	}

	const result = streamText({
		model: opencode.chatModel('minimax-m2.5'),
		system: `You are Meridian, an expert analyst for agentic commerce simulations. You analyze protocol performance across ACP, AP2, x402, MPP, and ATXP. Be precise with data, highlight surprising patterns, keep responses concise.\n\nSimulation context:\n${context || 'No context.'}`,
		messages,
	});

	return result.toDataStreamResponse();
};
