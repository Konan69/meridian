import { BigNumber } from "bignumber.js";
import {
  type Account,
  type AccountId,
  type AuthorizeParams,
  type AuthorizeResult,
  type Chain,
  type Currency,
  type Destination,
  type PaymentIdentifier,
  type PaymentMaker,
  type Source,
} from "@atxp/common";
import { getPolygonUSDCAddress } from "@atxp/client";
import {
  createWalletClient,
  encodeFunctionData,
  http,
  publicActions,
  type Hex,
  type WalletClient,
} from "viem";
import { privateKeyToAccount, type PrivateKeyAccount } from "viem/accounts";
import { polygon, polygonAmoy, type Chain as ViemChain } from "viem/chains";

const USDC_DECIMALS = 6;
const ERC20_ABI = [
  {
    constant: false,
    inputs: [
      { name: "_to", type: "address" },
      { name: "_value", type: "uint256" },
    ],
    name: "transfer",
    outputs: [{ name: "", type: "bool" }],
    type: "function",
  },
] as const;

function toBase64Url(data: string): string {
  return Buffer.from(data)
    .toString("base64")
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
}

function chainForId(chainId: number): {
  networkName: Chain;
  viemChain: ViemChain;
} {
  switch (chainId) {
    case 137:
      return { networkName: "polygon", viemChain: polygon };
    case 80002:
      return { networkName: "polygon_amoy", viemChain: polygonAmoy };
    default:
      throw new Error(
        `Unsupported Polygon chain ID: ${chainId}. Expected 137 or 80002`,
      );
  }
}

class PolygonPaymentMaker implements PaymentMaker {
  private readonly walletClient: WalletClient;
  private readonly account: PrivateKeyAccount;
  private readonly chainId: number;
  private readonly destinationChain: Chain;

  constructor(
    walletClient: WalletClient,
    account: PrivateKeyAccount,
    chainId: number,
    destinationChain: Chain,
  ) {
    this.walletClient = walletClient;
    this.account = account;
    this.chainId = chainId;
    this.destinationChain = destinationChain;
  }

  getSourceAddress(_params: {
    amount: BigNumber;
    currency: Currency;
    receiver: string;
    memo: string;
  }): string {
    return this.account.address;
  }

  async generateJWT(params: {
    paymentRequestId: string;
    codeChallenge: string;
    accountId?: AccountId | null;
  }): Promise<string> {
    const header = toBase64Url(JSON.stringify({ alg: "ES256K" }));
    const payload = toBase64Url(
      JSON.stringify({
        sub: this.account.address,
        iss: "accounts.atxp.ai",
        aud: "https://auth.atxp.ai",
        iat: Math.floor(Date.now() / 1000),
        exp: Math.floor(Date.now() / 1000) + 60 * 60,
        code_challenge: params.codeChallenge,
        payment_request_id: params.paymentRequestId,
        ...(params.accountId ? { account_id: params.accountId } : {}),
      }),
    );
    const message = `${header}.${payload}`;
    const signature = await this.walletClient.signMessage({
      account: this.account,
      message: { raw: Buffer.from(message, "utf8") },
    });
    return `${header}.${payload}.${toBase64Url(signature)}`;
  }

  async makePayment(
    destinations: Destination[],
    _memo: string,
    _paymentRequestId?: string,
  ): Promise<PaymentIdentifier | null> {
    const polygonDestinations = destinations.filter(
      (destination) => destination.chain === this.destinationChain,
    );
    if (polygonDestinations.length === 0) {
      return null;
    }

    const destination = polygonDestinations[0];
    if (destination.currency !== "USDC") {
      throw new Error(
        `Unsupported currency ${destination.currency}; Polygon payer only supports USDC`,
      );
    }

    const amountInUnits = BigInt(
      destination.amount.multipliedBy(10 ** USDC_DECIMALS).toFixed(0),
    );
    const usdcAddress = getPolygonUSDCAddress(this.chainId);
    const extended = this.walletClient.extend(publicActions);
    const txHash = await extended.sendTransaction({
      account: this.account,
      chain: this.walletClient.chain,
      to: usdcAddress as `0x${string}`,
      data: encodeFunctionData({
        abi: ERC20_ABI,
        functionName: "transfer",
        args: [destination.address as `0x${string}`, amountInUnits],
      }),
    });

    const receipt = await extended.waitForTransactionReceipt({ hash: txHash });
    if (receipt.status !== "success") {
      throw new Error(`Polygon payment failed for transaction ${txHash}`);
    }

    return {
      transactionId: txHash,
      chain: this.destinationChain,
      currency: "USDC",
    };
  }
}

export class MeridianPolygonServerAccount implements Account {
  readonly usesAccountsAuthorize = false;
  readonly paymentMakers: PaymentMaker[];
  private readonly accountId: AccountId;
  private readonly account: PrivateKeyAccount;
  private readonly destinationChain: Chain;

  constructor(polygonRpcUrl: string, sourceSecretKey: string, chainId: number = 137) {
    if (!polygonRpcUrl) {
      throw new Error("Polygon RPC URL is required");
    }
    if (!sourceSecretKey) {
      throw new Error("Polygon private key is required");
    }

    const { networkName, viemChain } = chainForId(chainId);
    this.account = privateKeyToAccount(sourceSecretKey as Hex);
    this.destinationChain = networkName;
    this.accountId = `${networkName}:${this.account.address}`;

    const walletClient = createWalletClient({
      account: this.account,
      chain: viemChain,
      transport: http(polygonRpcUrl),
    });
    this.paymentMakers = [
      new PolygonPaymentMaker(walletClient, this.account, chainId, networkName),
    ];
  }

  async getAccountId(): Promise<AccountId> {
    return this.accountId;
  }

  async getSources(): Promise<Source[]> {
    return [
      {
        address: this.account.address,
        chain: this.destinationChain,
        walletType: "eoa",
      },
    ];
  }

  async createSpendPermission(_resourceUrl: string): Promise<string | null> {
    return null;
  }

  async authorize(params: AuthorizeParams): Promise<AuthorizeResult> {
    if (!params.protocols || params.protocols.length === 0) {
      throw new Error("MeridianPolygonServerAccount: protocols array must not be empty");
    }
    const protocol = params.protocols.find((candidate) => candidate === "atxp");
    if (!protocol) {
      throw new Error(
        `MeridianPolygonServerAccount only supports atxp, got: ${params.protocols.join(", ")}`,
      );
    }
    if (!params.amount) {
      throw new Error("MeridianPolygonServerAccount: amount is required");
    }
    if (!params.destination) {
      throw new Error("MeridianPolygonServerAccount: destination is required");
    }

    const destination: Destination = {
      chain: this.destinationChain,
      currency: "USDC",
      address: params.destination,
      amount: new BigNumber(params.amount),
    };

    const result = await this.paymentMakers[0].makePayment(
      [destination],
      params.memo ?? "",
    );
    if (!result) {
      throw new Error("MeridianPolygonServerAccount: payment execution returned no result");
    }

    return {
      protocol,
      credential: JSON.stringify({
        transactionId: result.transactionId,
        chain: result.chain,
        currency: result.currency,
      }),
    };
  }
}
