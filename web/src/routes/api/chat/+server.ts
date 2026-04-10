import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { streamText } from "ai";
import type { RequestHandler } from "./$types";
import { env } from "$env/dynamic/private";

const opencode = createOpenAICompatible({
  name: "opencode-zen",
  baseURL: "https://opencode.ai/zen/v1",
  headers: {
    Authorization: `Bearer ${env.OPENCODE_API_KEY ?? ""}`,
  },
});

export const POST: RequestHandler = async ({ request }) => {
  const { messages, context, supportedProtocols } = await request.json();

  if (!env.OPENCODE_API_KEY) {
    return new Response(JSON.stringify({ error: "OPENCODE_API_KEY not configured" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  const result = streamText({
    model: opencode.chatModel("minimax-m2.5"),
    system: `You are Meridian, an expert analyst for agentic commerce simulations. Only speak as if a protocol is live when the runtime actually reports it as live. Current engine-supported protocols: ${
      Array.isArray(supportedProtocols) && supportedProtocols.length > 0
        ? supportedProtocols.join(", ")
        : "none reported"
    }. Be precise with data, highlight surprising patterns, keep responses concise.\n\nSimulation context:\n${context || "No context."}`,
    messages,
  });

  return result.toTextStreamResponse();
};
