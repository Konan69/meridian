import "dotenv/config";
import { serve } from "@hono/node-server";
import { Hono, type Context } from "hono";
import { cors } from "hono/cors";
import { atxpClient, getPolygonUSDCAddress } from "@atxp/client";
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
  MemoryOAuthDb,
  OAuthResourceClient,
  extractNetworkFromAccountId,
  paymentRequiredError,
  type AccountId,
  type PaymentDestination,
  type Source,
  type AuthorizationServerUrl,
  type PaymentProtocol,
} from "@atxp/common";
import { createPublicClient, erc20Abi, formatEther, formatUnits, http } from "viem";
import { polygonAmoy } from "viem/chains";
import { z } from "zod";
import {
  createPayerAccountFromEnvForActor,
  getPayerModeFromEnv,
  isCdpAccountSharedFromEnv,
  parsePayerMode,
} from "./payerAccount.js";
import {
  DirectTransferRejectedError,
  normalizeDirectTransferRequest,
  settleDirectTransfer,
} from "./directTransfer.js";
import { runtimeStatusForPayerMode } from "./funding.js";

const port = process.env.PORT ? parseInt(process.env.PORT, 10) : 3010;
type AppBindings = {
  Variables: {
    parsedBody?: unknown;
  };
};

type RuntimeMode = "unsupported" | "direct_settle" | "mcp_execute";

function runtimeReadyForPayerMode(payerMode: string): {
  runtimeMode: RuntimeMode;
  reason: string;
} {
  if (payerMode === "atxp") {
    return {
      runtimeMode: "direct_settle",
      reason: "ATXP payer mode supports Meridian's direct verify/settle runtime path",
    };
  }

  if (payerMode === "polygon") {
    return {
      runtimeMode: "mcp_execute",
      reason: "Polygon Amoy payer mode uses the official ATXP MCP payment-request flow",
    };
  }

  return {
    runtimeMode: "unsupported",
    reason: `${payerMode} is not runtime-ready for Meridian`,
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

type RuntimeProbeStatus = {
  checkedAt: number;
  runtimeReady: boolean;
  runtimeMode: RuntimeMode;
  reason: string;
};

const RUNTIME_PROBE_TTL_MS = 60_000;
let runtimeProbeCache: RuntimeProbeStatus | null = null;

async function probeRuntimeReadiness(destination: string): Promise<{
  runtimeReady: boolean;
  runtimeMode: RuntimeMode;
  reason: string;
}> {
  const payerMode = getPayerModeFromEnv();
  const payerModeStatus = runtimeReadyForPayerMode(payerMode);
  if (payerModeStatus.runtimeMode === "unsupported") {
    return {
      runtimeReady: false,
      ...payerModeStatus,
    };
  }

  if (payerModeStatus.runtimeMode === "mcp_execute") {
    const payer = createPayerAccountFromEnvForActor("__meridian_runtime_probe");
    const sources = await payer.getSources();
    const source = sources.find((entry) => entry.chain === "polygon_amoy") ?? sources[0];
    if (!source) {
      return {
        runtimeReady: false,
        runtimeMode: "mcp_execute",
        reason: "Polygon Amoy payer wallet has no usable source address",
      };
    }

    const rpcUrl = ensureEnv("ATXP_POLYGON_RPC_URL");
    const client = createPublicClient({
      chain: polygonAmoy,
      transport: http(rpcUrl),
    });
    try {
      const [polBalance, usdcBalance] = await Promise.all([
        client.getBalance({ address: source.address as `0x${string}` }),
        client.readContract({
          address: getPolygonUSDCAddress(80002) as `0x${string}`,
          abi: erc20Abi,
          functionName: "balanceOf",
          args: [source.address as `0x${string}`],
        }),
      ]);
      const hasPol = polBalance > 0n;
      const hasUsdc = usdcBalance > 0n;
      if (hasPol && hasUsdc) {
        return {
          runtimeReady: true,
          runtimeMode: "mcp_execute",
          reason: `Polygon Amoy payer wallet funded with ${formatEther(polBalance)} POL and ${formatUnits(usdcBalance, 6)} USDC`,
        };
      }
      const missing = [
        hasPol ? null : "POL gas",
        hasUsdc ? null : "USDC",
      ].filter(Boolean).join(" and ");
      return {
        runtimeReady: false,
        runtimeMode: "mcp_execute",
        reason: `Polygon Amoy payer wallet needs ${missing}`,
      };
    } catch (error) {
      return {
        runtimeReady: false,
        runtimeMode: "mcp_execute",
        reason: `Polygon Amoy readiness check failed: ${error instanceof Error ? error.message : String(error)}`,
      };
    }
  }

  try {
    const payer = createPayerAccountFromEnvForActor("__meridian_runtime_probe");
    await payer.authorize({
      protocols: ["atxp"],
      amount: new BigNumber(0.01),
      destination,
      memo: "meridian-runtime-probe",
    });
    return {
      runtimeReady: true,
      ...payerModeStatus,
    };
  } catch (error) {
    return {
      runtimeReady: false,
      runtimeMode: "direct_settle",
      reason: `ATXP authorize probe failed: ${error instanceof Error ? error.message : String(error)}`,
    };
  }
}

async function getRuntimeProbeStatus(destination: string): Promise<RuntimeProbeStatus> {
  if (runtimeProbeCache && Date.now() - runtimeProbeCache.checkedAt < RUNTIME_PROBE_TTL_MS) {
    return runtimeProbeCache;
  }

  const probe = await probeRuntimeReadiness(destination);
  runtimeProbeCache = {
    checkedAt: Date.now(),
    ...probe,
  };
  return runtimeProbeCache;
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
  requestPayment: (amountUsd: number) => Promise<void> = async (amountUsd: number) => {
    await runWithPaymentContext(async () => {
      await requirePayment({ price: new BigNumber(amountUsd) });
    });
  },
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
      console.log(
        "[atxp-tool] inside payment context",
        JSON.stringify({
          hasConfig: Boolean(getATXPConfig()),
          accountId: atxpAccountId(),
        }),
      );
      await requestPayment(amountUsd);
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

async function createPaymentRequirement(
  config: ReturnType<typeof buildServerConfig>,
  sourceAccountId: AccountId,
  amountUsd: number,
): Promise<string> {
  const destinationAccountId = await config.destination.getAccountId();
  const destinationSources = await config.destination.getSources();
  const sourceNetwork = extractNetworkFromAccountId(sourceAccountId);
  const destinationSource =
    destinationSources.find((source) => source.chain === sourceNetwork) ??
    (sourceNetwork === "polygon_amoy"
      ? destinationSources.find((source) => source.chain === "polygon")
      : null) ??
    (sourceNetwork === "base_sepolia"
      ? destinationSources.find((source) => source.chain === "base")
      : null) ??
    (sourceNetwork === "world_sepolia"
      ? destinationSources.find((source) => source.chain === "world")
      : null) ??
    destinationSources[0];
  if (!destinationSource) {
    throw new Error("No destination source available for ATXP payment request");
  }
  const options = [{
    network: sourceNetwork === "polygon_amoy" ? "polygon" : sourceNetwork,
    currency: config.currency,
    address: destinationSource.address,
    amount: new BigNumber(amountUsd),
  }];

  return await config.paymentServer.createPaymentRequest({
    options,
    sourceAccountId,
    destinationAccountId,
    payeeName: config.payeeName,
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

type ExecuteAtxpRequest = {
  actorId: string;
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

function payerModeFromRequest(request: Request) {
  const requested = new URL(request.url).searchParams.get("mode");
  return requested ? parsePayerMode(requested.trim().toLowerCase()) : getPayerModeFromEnv();
}

async function main() {
  const atxpConnectionString = ensureEnv("ATXP_CONNECTION_STRING");
  const payeeAccount = new ATXPAccount(atxpConnectionString);
  const { accountId, token } = parseAtxpConnectionString(atxpConnectionString);
  const payeeSources = await payeeAccount.getSources();
  const payerMode = getPayerModeFromEnv();
  const baseSource =
    payeeSources.find((source: Source) => source.chain === "base") ?? payeeSources[0];
  if (!baseSource) {
    throw new Error("ATXP payee account has no usable sources");
  }
  const polygonSource =
    payeeSources.find((source: Source) => source.chain === "polygon") ?? baseSource;
  const activePayeeSource = payerMode === "polygon" ? polygonSource : baseSource;
  const activePayeeAccountId =
    payerMode === "polygon"
      ? (`polygon:${activePayeeSource.address}` as AccountId)
      : (`base:${activePayeeSource.address}` as AccountId);
  const payeeAddress = activePayeeSource.address;
  const destination: PaymentDestination = new StaticDestination(
    activePayeeAccountId,
    [activePayeeSource],
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

  app.get("/health", async (c) => {
    const payerMode = payerModeFromRequest(c.req.raw);
    const runtime = await runtimeStatusForPayerMode(payerMode);
    const runtimeReady = runtime.supportsDirectSettle;
    return c.json({
      status: "ok",
      service: "meridian-atxp",
      authServer,
      payerMode,
      runtimeReady,
      runtimeMode: runtimeReady ? "direct_settle" : "unsupported",
      supportsDirectSettle: runtime.supportsDirectSettle,
      runtimeReadyReason: runtime.reason,
      funding: runtime,
      timestamp: new Date().toISOString(),
    });
  });

  app.get("/funding", async (c) => {
    const payerMode = payerModeFromRequest(c.req.raw);
    return c.json(await runtimeStatusForPayerMode(payerMode));
  });

  app.post("/atxp/authorize", async (c) => {
    try {
      const body = (await c.req.json()) as Partial<AuthorizeAtxpRequest>;
      if (!body.actorId || !body.merchant || typeof body.amountUsd !== "number") {
        return c.json({ error: "actorId, merchant, and amountUsd are required" }, 400);
      }

      const payerMode = getPayerModeFromEnv();
      const authorizeDestination = payerMode === "atxp" ? accountId : payeeAddress;
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
        sharedAccount: payerMode === "cdp-base" ? isCdpAccountSharedFromEnv() : true,
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
      const request = normalizeDirectTransferRequest(body);

      const payerMode = getPayerModeFromEnv();
      const settled = await settleDirectTransfer({
        authServer,
        logger: config.logger,
        destinationAccountId: `atxp:${accountId}`,
        payerMode,
        payeeSources,
        request,
        credential,
      });
      return c.json({
        ok: true,
        merchant: request.merchant,
        amountUsd: request.amountUsd,
        txHash: settled.txHash,
        settledAmount: settled.settledAmount,
        verificationMode: settled.verificationMode,
        alreadySettled: settled.alreadySettled ?? false,
      });
    } catch (error) {
      if (error instanceof DirectTransferRejectedError) {
        return c.json({ error: error.message }, error.status as 400 | 402 | 409 | 500);
      }
      return c.json(
        {
          error: error instanceof Error ? error.message : String(error),
        },
        500,
      );
    }
  });

  app.post("/atxp/execute", async (c) => {
    try {
      const body = (await c.req.json()) as Partial<ExecuteAtxpRequest>;
      if (!body.actorId || !body.merchant || typeof body.amountUsd !== "number") {
        return c.json({ error: "actorId, merchant, and amountUsd are required" }, 400);
      }

      const payerMode = getPayerModeFromEnv();
      if (payerMode === "polygon") {
        const authorizationServer = await (config.oAuthClient as unknown as {
          authorizationServerFromUrl: (url: URL) => Promise<Record<string, unknown>>;
          getClientCredentials: (authorizationServer: Record<string, unknown>) => Promise<unknown>;
        }).authorizationServerFromUrl(new URL(authServer));
        await (config.oAuthClient as unknown as {
          getClientCredentials: (authorizationServer: Record<string, unknown>) => Promise<unknown>;
        }).getClientCredentials(authorizationServer);

        const account = createPayerAccountFromEnvForActor(body.actorId);
        const accountId = await account.getAccountId();
        const payerSources = await account.getSources();
        const payerAddress = payerSources[0]?.address;
        const paymentId = await createPaymentRequirement(config, accountId, body.amountUsd);
        const paymentMaker = account.paymentMakers[0];
        if (!paymentMaker) {
          return c.json({ error: "No Polygon payment maker configured" }, 500);
        }

        const paymentResult = await paymentMaker.makePayment(
          [
            {
              chain: "polygon",
              currency: "USDC",
              address: payeeAddress,
              amount: new BigNumber(body.amountUsd),
            },
          ],
          body.memo ?? `meridian-atxp:${body.actorId}:${body.merchant}`,
          paymentId,
        );
        if (!paymentResult) {
          return c.json({ error: "Polygon payment maker returned no result" }, 502);
        }

        const candidateAccountIds = Array.from(
          new Set(
            [
              accountId,
              payerAddress ?? null,
              payerAddress ? `polygon:${payerAddress}` : null,
              payerAddress ? `polygon_amoy:${payerAddress}` : null,
            ].filter((value): value is string => Boolean(value)),
          ),
        );

        let lastSettleError = "ATXP payment completion failed";
        let settled = false;
        for (const candidateAccountId of candidateAccountIds) {
          const jwt = await paymentMaker.generateJWT({
            paymentRequestId: paymentId,
            codeChallenge: "",
            accountId: candidateAccountId as AccountId,
          });
          const settlePayload = {
            transactionId: paymentResult.transactionId,
            chain: "polygon",
            currency: paymentResult.currency,
            accountId: candidateAccountId,
            account_id: candidateAccountId,
            sourceAccountId: candidateAccountId,
            source_account_id: candidateAccountId,
          };
          console.log("[atxp-execute] settle payload", JSON.stringify(settlePayload));
          const settleResponse = await fetch(`${authServer}/payment-request/${paymentId}`, {
            method: "PUT",
            headers: {
              authorization: `Bearer ${jwt}`,
              "content-type": "application/json",
            },
            body: JSON.stringify(settlePayload),
          });
          const settleBody = await settleResponse.text();
          if (settleResponse.ok) {
            settled = true;
            break;
          }
          lastSettleError = `ATXP: payment to ${authServer}/payment-request/${paymentId} failed: HTTP ${settleResponse.status} ${settleBody}`;
        }

        if (!settled) {
          return c.json(
            {
              error: lastSettleError,
            },
            500,
          );
        }

        return c.json({
          ok: true,
          protocol: "atxp",
          payerMode,
          merchant: body.merchant,
          amountUsd: body.amountUsd,
          paymentEvents: [
            {
              transactionHash: paymentResult.transactionId,
              network: paymentResult.chain,
            },
          ],
          result: {
            content: [
              {
                type: "text",
                text: `ATXP payment confirmed for ${body.merchant}. Amount: ${body.amountUsd.toFixed(2)} USD.${body.memo ? ` Memo: ${body.memo}` : ""}`,
              },
            ],
          },
        });
      }

      const paymentEvents: Array<Record<string, unknown>> = [];
      const paymentFailures: string[] = [];
      const authFailures: string[] = [];
      const client = await atxpClient({
        mcpServer: `http://localhost:${port}/mcp`,
        account: createPayerAccountFromEnvForActor(body.actorId),
        approvePayment: async () => true,
        onPayment: async (data) => {
          paymentEvents.push(data as Record<string, unknown>);
        },
        onPaymentFailure: async (context) => {
          paymentFailures.push(
            context.error instanceof Error ? context.error.message : String(context.error),
          );
        },
        onAuthorizeFailure: async ({ error }) => {
          authFailures.push(error instanceof Error ? error.message : String(error));
        },
      });

      const result = await client.callTool({
        name: "stablecoin_transfer",
        arguments: {
          merchant: body.merchant,
          amountUsd: body.amountUsd,
          memo: body.memo,
        },
      });

      if ("isError" in result && result.isError) {
        const contentText = Array.isArray(result.content)
          ? result.content
              .map((item) => ("text" in item ? String(item.text) : JSON.stringify(item)))
              .join("\n")
          : "ATXP MCP execute failed";
        return c.json(
          {
            error: contentText,
            payerMode,
            paymentEvents,
            paymentFailures,
            authFailures,
          },
          502,
        );
      }

      return c.json({
        ok: true,
        protocol: "atxp",
        payerMode,
        merchant: body.merchant,
        amountUsd: body.amountUsd,
        paymentEvents,
        result,
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

      if (
        c.req.method === "POST" &&
        typeof parsedBody === "object" &&
        parsedBody !== null &&
        "method" in parsedBody &&
        parsedBody.method === "tools/list"
      ) {
        const transport = new WebStandardStreamableHTTPServerTransport({
          sessionIdGenerator: undefined,
          enableJsonResponse: true,
        });
        const server = createMcpServer();
        await server.connect(transport);
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

      const sourceAccountId = (
        (tokenCheck.data as { account_id?: string; sub?: string } | null)?.account_id ??
        (getPayerModeFromEnv() === "polygon" && tokenCheck.data?.sub
          ? `polygon:${tokenCheck.data.sub}`
          : tokenCheck.data?.sub)
      ) as AccountId | undefined;
      console.log(
        "[atxp-route] token data",
        JSON.stringify({
          tokenData: tokenCheck.data,
          sourceAccountId,
        }),
      );
      const requestPayment = async (amountUsd: number): Promise<void> => {
        if (!sourceAccountId) {
          throw new Error("No source account id available for ATXP payment request");
        }
        await runWithPaymentContext(async () => {
          const paymentId = await createPaymentRequirement(config, sourceAccountId, amountUsd);
          throw paymentRequiredError(config.server, paymentId, new BigNumber(amountUsd));
        });
      };

      const transport = new WebStandardStreamableHTTPServerTransport({
        sessionIdGenerator: undefined,
        enableJsonResponse: true,
      });
      const server = createMcpServer(runWithPaymentContext, requestPayment);
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
