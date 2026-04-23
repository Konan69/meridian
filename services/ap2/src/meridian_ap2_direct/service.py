"""Meridian-owned AP2 service built on official AP2 types."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from ap2.types.mandate import (
    CartContents,
    CartMandate,
    IntentMandate,
    PaymentMandate,
    PaymentMandateContents,
)
from ap2.types.payment_receipt import PaymentReceipt, Success
from ap2.types.payment_request import (
    PaymentCurrencyAmount,
    PaymentDetailsInit,
    PaymentItem,
    PaymentMethodData,
    PaymentOptions,
    PaymentRequest,
    PaymentResponse,
)
from ecdsa import SECP256k1, BadSignatureError, SigningKey, VerifyingKey, util
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import uvicorn

from .contracts import canonical_hash, canonical_json, settlement_contract_errors


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _json_dumps(value: Any) -> bytes:
    return canonical_json(value)


def _canonical_hash(value: Any) -> str:
    return canonical_hash(value)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set")
    return value


def _derive_signing_key(master_seed: str, purpose: str, actor_id: str) -> SigningKey:
    digest = hmac.new(
        master_seed.encode(),
        f"{purpose}:{actor_id}".encode(),
        hashlib.sha256,
    ).digest()
    key_int = (int.from_bytes(digest, "big") % (SECP256k1.order - 1)) + 1
    return SigningKey.from_secret_exponent(key_int, curve=SECP256k1)


def _verify_key(signing_key: SigningKey) -> VerifyingKey:
    return signing_key.get_verifying_key()


def _sign_jwt(signing_key: SigningKey, payload: dict[str, Any], kid: str) -> str:
    header = {"alg": "ES256K", "typ": "JWT", "kid": kid}
    signing_input = f"{_base64url(_json_dumps(header))}.{_base64url(_json_dumps(payload))}"
    signature = signing_key.sign_deterministic(
        signing_input.encode(),
        hashfunc=hashlib.sha256,
        sigencode=util.sigencode_string,
    )
    return f"{signing_input}.{_base64url(signature)}"


def _verify_jwt(token: str, verifying_key: VerifyingKey) -> dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise ValueError("JWT must have 3 parts") from exc

    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = base64.urlsafe_b64decode(signature_b64 + "=" * (-len(signature_b64) % 4))
    try:
        verifying_key.verify(
            signature,
            signing_input,
            hashfunc=hashlib.sha256,
            sigdecode=util.sigdecode_string,
        )
    except BadSignatureError as exc:
        raise ValueError("invalid JWT signature") from exc

    payload = base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4))
    return json.loads(payload.decode())


class AuthorizeRequest(BaseModel):
    actor_id: str = Field(alias="actorId")
    merchant: str
    amount_usd: float = Field(alias="amountUsd")
    memo: str | None = None
    requires_confirmation: bool = Field(default=False, alias="requiresConfirmation")


class SettleRequest(BaseModel):
    merchant: str
    amount_usd: float = Field(alias="amountUsd")
    memo: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    runtime_ready: bool = Field(alias="runtimeReady")
    runtime_ready_reason: str = Field(alias="runtimeReadyReason")


def _usd(value: float) -> PaymentCurrencyAmount:
    return PaymentCurrencyAmount(currency="USD", value=round(value, 2))


def _build_intent(body: AuthorizeRequest) -> IntentMandate:
    return IntentMandate(
        user_cart_confirmation_required=body.requires_confirmation,
        natural_language_description=body.memo
        or f"Agent purchase from {body.merchant} for ${body.amount_usd:.2f}",
        merchants=[body.merchant],
        requires_refundability=False,
        intent_expiry=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )


def _build_cart(body: AuthorizeRequest) -> CartMandate:
    item = PaymentItem(label=body.memo or "Meridian AP2 purchase", amount=_usd(body.amount_usd))
    payment_request = PaymentRequest(
        method_data=[
            PaymentMethodData(
                supported_methods="https://meridian.dev/payment-methods/ap2-runtime"
            )
        ],
        details=PaymentDetailsInit(
            id=f"ap2_req_{uuid.uuid4().hex[:12]}",
            display_items=[item],
            total=item,
        ),
        options=PaymentOptions(
            request_shipping=False,
            request_payer_email=False,
            request_payer_name=False,
            request_payer_phone=False,
        ),
    )
    return CartMandate(
        contents=CartContents(
            id=f"ap2_cart_{uuid.uuid4().hex[:12]}",
            user_cart_confirmation_required=body.requires_confirmation,
            payment_request=payment_request,
            cart_expiry=(datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            merchant_name=body.merchant,
        )
    )


def _build_payment_mandate(body: AuthorizeRequest) -> PaymentMandate:
    item = PaymentItem(label="Total", amount=_usd(body.amount_usd))
    payment_response = PaymentResponse(
        request_id=f"ap2_req_{uuid.uuid4().hex[:12]}",
        method_name="https://meridian.dev/payment-methods/ap2-runtime",
        details={"merchant": body.merchant, "memo": body.memo},
    )
    return PaymentMandate(
        payment_mandate_contents=PaymentMandateContents(
            payment_mandate_id=f"ap2_paymand_{uuid.uuid4().hex[:12]}",
            payment_details_id=payment_response.request_id,
            payment_details_total=item,
            payment_response=payment_response,
            merchant_agent=body.merchant,
        )
    )


def create_app() -> FastAPI:
    master_seed = _require_env("AP2_MASTER_SEED")

    app = FastAPI(title="meridian-ap2", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return HealthResponse(
            status="ok",
            service="meridian-ap2",
            runtimeReady=True,
            runtimeReadyReason="Meridian AP2 service is built on official AP2 types and mandate signing",
        ).model_dump(by_alias=True)

    @app.post("/ap2/authorize")
    async def authorize(body: AuthorizeRequest) -> dict[str, Any]:
        issuer_key = _derive_signing_key(master_seed, "ap2:issuer", body.actor_id)
        user_key = _derive_signing_key(master_seed, "ap2:user", body.actor_id)

        intent = _build_intent(body)
        cart = _build_cart(body)
        payment = _build_payment_mandate(body)

        cart_hash = _canonical_hash(cart.contents.model_dump(mode="json"))
        payment_hash = _canonical_hash(payment.payment_mandate_contents.model_dump(mode="json"))

        merchant_claims = {
            "iss": f"merchant:{body.merchant}",
            "sub": f"merchant:{body.merchant}",
            "aud": "meridian-ap2-processor",
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
            "jti": f"cart-auth-{uuid.uuid4().hex[:12]}",
            "cart_hash": cart_hash,
        }
        cart.merchant_authorization = _sign_jwt(
            issuer_key, merchant_claims, kid=f"issuer-{body.actor_id[:8]}"
        )

        user_claims = {
            "iss": f"user:{body.actor_id}",
            "sub": f"user:{body.actor_id}",
            "aud": "meridian-ap2-processor",
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
            "jti": f"user-auth-{uuid.uuid4().hex[:12]}",
            "cart_hash": cart_hash,
            "payment_hash": payment_hash,
            "intent_hash": _canonical_hash(intent.model_dump(mode="json")),
        }
        payment.user_authorization = _sign_jwt(
            user_key, user_claims, kid=f"user-{body.actor_id[:8]}"
        )

        credential = {
            "actorId": body.actor_id,
            "merchant": body.merchant,
            "amountUsd": body.amount_usd,
            "intentMandate": intent.model_dump(mode="json"),
            "cartMandate": cart.model_dump(mode="json"),
            "paymentMandate": payment.model_dump(mode="json"),
        }

        return {
            "ok": True,
            "protocol": "ap2",
            "credential": json.dumps(credential, separators=(",", ":")),
            "actorId": body.actor_id,
            "merchant": body.merchant,
            "amountUsd": body.amount_usd,
        }

    @app.post("/ap2/settle")
    async def settle(
        body: SettleRequest,
        x_ap2_credential: str | None = Header(default=None, alias="x-ap2-credential"),
    ) -> dict[str, Any]:
        if not x_ap2_credential:
            raise HTTPException(status_code=400, detail="x-ap2-credential header is required")

        try:
            credential = json.loads(x_ap2_credential)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid AP2 credential JSON") from exc

        contract_errors = settlement_contract_errors(credential, body.merchant, body.amount_usd)
        if contract_errors:
            raise HTTPException(status_code=400, detail=contract_errors[0])

        actor_id = credential["actorId"]
        issuer_key = _derive_signing_key(master_seed, "ap2:issuer", actor_id)
        user_key = _derive_signing_key(master_seed, "ap2:user", actor_id)

        cart = CartMandate.model_validate(credential["cartMandate"])
        payment = PaymentMandate.model_validate(credential["paymentMandate"])

        cart_hash = _canonical_hash(cart.contents.model_dump(mode="json"))
        payment_hash = _canonical_hash(payment.payment_mandate_contents.model_dump(mode="json"))

        merchant_claims = _verify_jwt(
            cart.merchant_authorization or "", _verify_key(issuer_key)
        )
        user_claims = _verify_jwt(
            payment.user_authorization or "", _verify_key(user_key)
        )

        if merchant_claims.get("cart_hash") != cart_hash:
            raise HTTPException(status_code=400, detail="merchant authorization cart hash mismatch")
        if user_claims.get("cart_hash") != cart_hash:
            raise HTTPException(status_code=400, detail="user authorization cart hash mismatch")
        if user_claims.get("payment_hash") != payment_hash:
            raise HTTPException(status_code=400, detail="user authorization payment hash mismatch")
        if cart.contents.merchant_name != body.merchant:
            raise HTTPException(status_code=400, detail="merchant mismatch")
        total_value = cart.contents.payment_request.details.total.amount.value
        if round(total_value, 2) != round(body.amount_usd, 2):
            raise HTTPException(status_code=400, detail="amount mismatch")

        receipt = PaymentReceipt(
            payment_mandate_id=payment.payment_mandate_contents.payment_mandate_id,
            payment_id=f"ap2_receipt_{uuid.uuid4().hex[:12]}",
            amount=_usd(body.amount_usd),
            payment_status=Success(
                merchant_confirmation_id=f"merchant_{uuid.uuid4().hex[:12]}",
                psp_confirmation_id=f"psp_{uuid.uuid4().hex[:12]}",
                network_confirmation_id=f"network_{uuid.uuid4().hex[:12]}",
            ),
            payment_method_details=payment.payment_mandate_contents.payment_response.details,
        )

        return {
            "ok": True,
            "merchant": body.merchant,
            "amountUsd": body.amount_usd,
            "receipt": receipt.model_dump(mode="json"),
            "paymentId": receipt.payment_id,
        }

    return app


def main() -> None:
    port = int(os.environ.get("PORT", "3040"))
    uvicorn.run(create_app(), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
