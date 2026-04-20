import { createAnthropic } from "@ai-sdk/anthropic";
import { generateText } from "ai";
import type { RequestHandler } from "./$types";
import { env } from "$env/dynamic/private";

const OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1";
const DEFAULT_GO_MODEL = "minimax-m2.5";

type ChatStatus = {
  enabled: boolean;
  provider: "opencode-go";
  model: string;
  baseURL: string;
  reason?: string;
};

function getApiKey(): string {
  return env.OPENCODE_GO_API_KEY ?? env.OPENCODE_API_KEY ?? "";
}

function getModel(): string {
  return env.OPENCODE_GO_MODEL ?? DEFAULT_GO_MODEL;
}

function getChatStatus(): ChatStatus {
  const apiKey = getApiKey();
  return {
    enabled: Boolean(apiKey),
    provider: "opencode-go",
    model: getModel(),
    baseURL: OPENCODE_GO_BASE_URL,
    ...(apiKey
      ? {}
      : {
          reason: "OPENCODE_GO_API_KEY or OPENCODE_API_KEY not configured",
        }),
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export const GET: RequestHandler = async () => json(getChatStatus());

export const POST: RequestHandler = async ({ request }) => {
  const status = getChatStatus();
  if (!status.enabled) {
    return json({ error: status.reason ?? "Chat provider not configured", ...status }, 503);
  }

  const { messages, context, supportedProtocols } = await request.json();
  if (!Array.isArray(messages) || messages.length === 0) {
    return json({ error: "messages must be a non-empty array", ...status }, 400);
  }

  try {
    const anthropic = createAnthropic({
      apiKey: getApiKey(),
      baseURL: OPENCODE_GO_BASE_URL,
    });

    const result = await generateText({
      model: anthropic(getModel()),
      system: `You are Meridian, an expert analyst for agentic commerce simulations. Only speak as if a protocol is live when the runtime actually reports it as live. Current engine-supported protocols: ${
        Array.isArray(supportedProtocols) && supportedProtocols.length > 0
          ? supportedProtocols.join(", ")
          : "none reported"
      }. Be precise with data, highlight surprising patterns, keep responses concise.\n\nSimulation context:\n${context || "No context."}`,
      messages,
    });

    return json({
      text: result.text,
      provider: status.provider,
      model: status.model,
    });
  } catch (error) {
    const providerError = error as {
      statusCode?: number;
      responseBody?: string;
      message?: string;
      data?: { error?: { message?: string; type?: string } };
    };
    const providerMessage =
      providerError?.data?.error?.message ??
      providerError?.message ??
      "Chat request failed";
    const hasCreditsError =
      providerMessage.toLowerCase().includes("insufficient balance") ||
      providerError?.data?.error?.type === "CreditsError";
    const responseStatus =
      typeof providerError?.statusCode === "number"
        ? hasCreditsError && providerError.statusCode === 401
          ? 402
          : providerError.statusCode
        : 502;

    return json(
      {
        error: providerMessage,
        provider: status.provider,
        model: status.model,
        providerStatus: providerError?.statusCode ?? null,
        responseBody: providerError?.responseBody ?? null,
      },
      responseStatus,
    );
  }
};
