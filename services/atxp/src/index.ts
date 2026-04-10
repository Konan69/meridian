import "dotenv/config";
import { serve } from "@hono/node-server";
import { Hono, type Context } from "hono";
import { cors } from "hono/cors";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { BigNumber } from "bignumber.js";
import {
  ProtocolSettlement,
  atxpAccountId,
  buildServerConfig,
  checkTokenWebApi,
  detectProtocol,
  getATXPConfig,
  getOAuthMetadata,
  getProtectedResourceMetadata,
  getResource,
  parseMcpRequestsWebApi,
  requirePayment,
  sendOAuthChallengeWebApi,
  sendOAuthMetadataWebApi,
  sendProtectedResourceMetadataWebApi,
  withATXPContext,
} from "@atxp/server";
import {
  ATXPAccount,
  AccountIdDestination,
  MemoryOAuthDb,
  OAuthResourceClient,
  type AccountId,
  type PaymentDestination,
  type Source,
  type AuthorizationServerUrl,
  type PaymentProtocol,
} from "@atxp/common";
import { z } from "zod";
import { createPayerAccountFromEnvForActor, getPayerModeFromEnv } from "./payerAccount.js";

const port = process.env.PORT ? parseInt(process.env.PORT, 10) : 3010;
type AppBindings = {
  Variables: {
    parsedBody?: unknown;
  };
};

function runtimeReadyForPayerMode(payerMode: string): {
  supportsDirectSettle: boolean;
  reason: string;
} {
  if (payerMode === "atxp") {
    return {
      supportsDirectSettle: true,
      reason: "ATXP payer mode supports Meridian's direct verify/settle runtime path",
    };
  }

  if (payerMode === "base" || payerMode === "polygon") {
    return {
      supportsDirectSettle: false,
      reason: `${payerMode} payer mode uses raw onchain transaction credentials and is not direct-settle-ready in Meridian`,
    };
  }

  return {
    supportsDirectSettle: false,
    reason: "cdp-base is Meridian-owned CDP glue and is not direct-settle-ready in Meridian runtime",
  };
}

function ensureEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function parseAtxpConnectionString(connectionString: string): {
  accountId: string;
  token: string;
} {
  const url = new URL(connectionString);
  const token = url.searchParams.get("connection_token");
  const accountId = url.searchParams.get("account_id");
  if (!token || !accountId) {
    throw new Error("ATXP connection string must include connection_token and account_id");
  }
  return { token, accountId };
}

class MeridianOAuthResourceClient extends OAuthResourceClient {
  override getRegistrationMetadata = async () => {
    return {
      redirect_uris: [this.callbackUrl],
      response_types: ["code"],
      grant_types: ["authorization_code", "refresh_token", "client_credentials"],
      token_endpoint_auth_method: "client_secret_post",
      client_name: `OAuth Client for ${this.callbackUrl}`,
    };
  };
}

class StaticDestination implements PaymentDestination {
  constructor(
    private readonly accountId: AccountId,
    private readonly sources: Source[],
  ) {}

  async getAccountId(): Promise<AccountId> {
    return this.accountId;
  }

  async getSources(): Promise<Source[]> {
    return this.sources;
  }
}

function createMcpServer(
  runWithPaymentContext: <T>(fn: () => Promise<T>) => Promise<T> = async <T>(
    fn: () => Promise<T>,
  ) => await fn(),
): McpServer {
  const server = new McpServer(
    {
      name: "meridian-atxp-direct",
      version: "0.1.0",
    },
    {
      capabilities: {
        logging: {},
        tools: {},
      },
    },
  );

  server.tool(
    "stablecoin_transfer",
    "Execute a paid stablecoin transfer-style tool through ATXP",
    {
      merchant: z.string().describe("Merchant or treasury target"),
      amountUsd: z.number().positive().describe("Amount in USD"),
      memo: z.string().optional().describe("Optional memo"),
    },
    async ({
      merchant,
      amountUsd,
      memo,
    }: {
      merchant: string;
      amountUsd: number;
      memo?: string;
    }): Promise<CallToolResult> => {
      console.log(
        "[atxp-tool] before requirePayment",
        JSON.stringify({
          hasConfig: Boolean(getATXPConfig()),
          accountId: atxpAccountId(),
          merchant,
          amountUsd,
        }),
      );
      await runWithPaymentContext(async () => {
        console.log(
          "[atxp-tool] inside payment context",
          JSON.stringify({
            hasConfig: Boolean(getATXPConfig()),
            accountId: atxpAccountId(),
          }),
        );
        await requirePayment({ price: BigNumber(amountUsd) });
      });
      return {
        content: [
          {
            type: "text",
            text: `ATXP payment confirmed for ${merchant}. Amount: ${amountUsd.toFixed(2)} USD.${memo ? ` Memo: ${memo}` : ""}`,
          },
        ],
      };
    },
  );

  return server;
}

function headersToObject(headers: Headers): Record<string, string> {
  return Object.fromEntries(headers.entries());
}

async function materializeResponse(response: Response): Promise<Response> {
  const body = await response.arrayBuffer();
  return new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

async function handleProtocolCredential(
  config: ReturnType<typeof buildServerConfig>,
  request: Request,
  protocol: PaymentProtocol,
  credential: string,
  next: () => Promise<Response>,
): Promise<Response> {
  const logger = config.logger;
  const settlement = new ProtocolSettlement(config.server, logger);

  logger.info(`Detected ${protocol} credential on retry request`);
  const verifyResult = await settlement.verify(protocol, credential);
  if (!verifyResult.valid) {
    logger.warn(`${protocol} credential verification failed`);
    return new Response(
      JSON.stringify({
        error: "invalid_payment",
        error_description: `${protocol} credential verification failed`,
      }),
      {
        status: 402,
        headers: { "content-type": "application/json" },
      },
    );
  }

  const response = await next();
  if (response.ok) {
    try {
      await settlement.settle(protocol, credential);
    } catch (error) {
      logger.error(
        `Failed to settle ${protocol} payment: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
  return response;
}

type DirectAtxpRequest = {
  merchant: string;
  amountUsd: number;
  memo?: string;
};

type AuthorizeAtxpRequest = {
  actorId: string;
  merchant: string;
  amountUsd: number;
  memo?: string;
};

async function main() {
  const atxpConnectionString = ensureEnv("ATXP_CONNECTION_STRING");
  const payeeAccount = new ATXPAccount(atxpConnectionString);
  const { accountId, token } = parseAtxpConnectionString(atxpConnectionString);
  const payeeSources = await payeeAccount.getSources();
  const baseSource =
    payeeSources.find((source: Source) => source.chain === "base") ?? payeeSources[0];
  if (!baseSource) {
    throw new Error("ATXP payee account has no usable sources");
  }
  const destination: PaymentDestination = new StaticDestination(
    `base:${baseSource.address}` as AccountId,
    [baseSource],
  );
  const authServer: AuthorizationServerUrl =
    (process.env.ATXP_SERVER as AuthorizationServerUrl | undefined) ?? "https://auth.atxp.ai";
  const oAuthDb = new MemoryOAuthDb();
  const oAuthClient = new MeridianOAuthResourceClient({
    db: oAuthDb,
    callbackUrl: `http://localhost:${port}/mcp`,
    allowInsecureRequests: process.env.NODE_ENV === "development",
    clientName: "Meridian ATXP Direct",
    atxpConnectionToken: token,
    registrationType: "client",
  });

  const config = buildServerConfig({
    destination,
    payeeName: "Meridian ATXP Direct",
    server: authServer,
    allowHttp: process.env.NODE_ENV === "development",
    mountPath: "/mcp",
    resource: `http://localhost:${port}/mcp`,
    oAuthDb,
    oAuthClient,
  });

  const app = new Hono<AppBindings>();
  app.use(
    "*",
    cors({
      origin: "*",
      allowMethods: ["GET", "POST", "OPTIONS"],
      allowHeaders: [
        "Content-Type",
        "Authorization",
        "x-payment",
        "accept",
        "mcp-session-id",
        "mcp-protocol-version",
      ],
      exposeHeaders: ["WWW-Authenticate", "mcp-session-id", "mcp-protocol-version"],
    }),
  );

  app.get("/health", (c) =>
    c.json((() => {
      const payerMode = getPayerModeFromEnv();
      const runtime = runtimeReadyForPayerMode(payerMode);
      return {
      status: "ok",
      service: "meridian-atxp",
      authServer,
      payerMode,
      supportsDirectSettle: runtime.supportsDirectSettle,
      runtimeReadyReason: runtime.reason,
      timestamp: new Date().toISOString(),
    }; })()),
  );

  app.post("/atxp/authorize", async (c) => {
    try {
      const body = (await c.req.json()) as Partial<AuthorizeAtxpRequest>;
      if (!body.actorId || !body.merchant || typeof body.amountUsd !== "number") {
        return c.json({ error: "actorId, merchant, and amountUsd are required" }, 400);
      }

      const payerMode = getPayerModeFromEnv();
      const authorizeDestination =
        payerMode === "atxp" ? accountId : baseSource.address;
      const payerAccount = createPayerAccountFromEnvForActor(body.actorId);
      const authorizeResult = await payerAccount.authorize({
        protocols: ["atxp"],
        amount: new BigNumber(body.amountUsd),
        destination: authorizeDestination,
        memo: body.memo ?? `meridian-atxp:${body.actorId}:${body.merchant}`,
      });

      return c.json({
        ok: true,
        protocol: authorizeResult.protocol,
        credential: authorizeResult.credential,
        actorId: body.actorId,
        merchant: body.merchant,
        amountUsd: body.amountUsd,
        destination: authorizeDestination,
        sharedAccount: payerMode !== "cdp-base",
      });
    } catch (error) {
      return c.json(
        {
          error: error instanceof Error ? error.message : String(error),
        },
        500,
      );
    }
  });

  app.post("/atxp/direct-transfer", async (c) => {
    try {
      const body = (await c.req.json()) as Partial<DirectAtxpRequest>;
      const credential =
        c.req.header("x-atxp-payment") ??
        c.req.header("authorization")?.replace(/^Bearer\s+/i, "");

      if (!credential) {
        return c.json({ error: "x-atxp-payment or Bearer credential is required" }, 400);
      }
      if (!body.merchant || typeof body.amountUsd !== "number") {
        return c.json({ error: "merchant and amountUsd are required" }, 400);
      }

      const settlement = new ProtocolSettlement(
        authServer,
        config.logger,
        fetch.bind(globalThis),
        `atxp:${accountId}`,
      );
      const valid = await settlement.verify("atxp", credential);
      if (!valid.valid) {
        return c.json({ error: "ATXP credential verification failed" }, 402);
      }

      const settled = await settlement.settle("atxp", credential);
      return c.json({
        ok: true,
        merchant: body.merchant,
        amountUsd: body.amountUsd,
        txHash: settled.txHash,
        settledAmount: settled.settledAmount,
      });
    } catch (error) {
      return c.json(
        {
          error: error instanceof Error ? error.message : String(error),
        },
        500,
      );
    }
  });

  const handleMcp = async (c: Context<AppBindings>) => {
    try {
      const requestUrl = new URL(c.req.url);
      const resource = getResource(config, requestUrl, headersToObject(c.req.raw.headers));

      if (requestUrl.pathname.startsWith("/mcp/.well-known/oauth-protected-resource")) {
        return c.json({
          resource: config.resource ?? `http://localhost:${port}/mcp`,
          resource_name: config.payeeName,
          authorization_servers: [config.server],
          bearer_methods_supported: ["header"],
          scopes_supported: ["read", "write"],
        });
      }

      const prm = getProtectedResourceMetadata(
        config,
        requestUrl,
        headersToObject(c.req.raw.headers),
      );
      const prmResponse = sendProtectedResourceMetadataWebApi(prm);
      if (prmResponse) {
        return prmResponse;
      }

      const oauth = await getOAuthMetadata(config, requestUrl);
      const oauthResponse = sendOAuthMetadataWebApi(oauth);
      if (oauthResponse) {
        return oauthResponse;
      }

      const parsedBody =
        c.req.method === "POST"
          ? await c.req.raw
              .clone()
              .json()
              .catch(() => undefined)
          : undefined;

      let requestForParsing: Request;
      if (c.req.method === "POST" && parsedBody !== undefined) {
        requestForParsing = new Request(c.req.raw, {
          method: "POST",
          body: JSON.stringify(parsedBody),
        });
      } else {
        requestForParsing = c.req.raw.clone();
      }

      const mcpRequests = await parseMcpRequestsWebApi(config, requestForParsing);

      if (mcpRequests.length === 0) {
        const transport = new WebStandardStreamableHTTPServerTransport({
          sessionIdGenerator: undefined,
          enableJsonResponse: true,
        });
        const server = createMcpServer();
        await server.connect(transport);
        const detected = detectProtocol({
          "x-payment": c.req.header("x-payment") ?? undefined,
          authorization: c.req.header("authorization") ?? undefined,
        });
        if (detected) {
          return await handleProtocolCredential(
            config,
            c.req.raw,
            detected.protocol,
            detected.credential,
            async () =>
              await materializeResponse(
                await transport.handleRequest(c.req.raw, {
                  parsedBody,
                }),
              ),
          );
        }

        return materializeResponse(
          await transport.handleRequest(c.req.raw, {
            parsedBody,
          }),
        );
      }

      const tokenCheck = await checkTokenWebApi(config, resource, c.req.raw);
      const challenge = sendOAuthChallengeWebApi(tokenCheck);
      if (challenge) {
        return challenge;
      }

      const runWithPaymentContext = async <T>(fn: () => Promise<T>): Promise<T> => {
        let result: T | undefined;
        await withATXPContext(config, resource, tokenCheck, async () => {
          console.log(
            "[atxp-route] entering ATXP context",
            JSON.stringify({
              hasConfig: Boolean(getATXPConfig()),
              accountId: atxpAccountId(),
              method: c.req.method,
            }),
          );
          result = await fn();
        });
        return result as T;
      };

      const transport = new WebStandardStreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
        enableJsonResponse: true,
      });
      const server = createMcpServer(runWithPaymentContext);
      await server.connect(transport);

      let response: Response | undefined;
      await withATXPContext(config, resource, tokenCheck, async () => {
        response = await materializeResponse(
          await transport.handleRequest(c.req.raw, {
            parsedBody,
          }),
        );
      });

      return (
        response ??
        c.json(
          {
            error: "server_error",
            error_description: "ATXP context completed without a response",
          },
          500,
        )
      );
    } catch (error) {
      config.logger.error(
        `Critical error in Hono ATXP handler: ${error instanceof Error ? error.message : String(error)}`,
      );
      return c.json(
        {
          error: "server_error",
          error_description: "An internal server error occurred",
        },
        500,
      );
    }
  };

  app.all("/mcp", handleMcp);
  app.all("/mcp/*", handleMcp);

  serve(
    {
      fetch: app.fetch,
      port,
    },
    (info) => {
      console.log(`meridian-atxp listening on http://localhost:${info.port}`);
    },
  );
}

main().catch((error) => {
  console.error("[atxp] failed to start", error);
  process.exit(1);
});
