"""Commerce actions — agents interact with the Rust engine over HTTP."""

from __future__ import annotations

import json
from typing import Optional

import aiohttp

from .types import PROTOCOL_FEE_FORMULAS, Protocol, TransactionRecord


class CommerceClient:
    """HTTP client for the Meridian Rust commerce engine."""

    def __init__(self, engine_url: str = "http://localhost:4080"):
        self.engine_url = engine_url
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def health(self) -> bool:
        try:
            session = await self._get_session()
            async with session.get(f"{self.engine_url}/health") as resp:
                return resp.status == 200
        except Exception:
            return False

    async def get_products(self) -> list[dict]:
        session = await self._get_session()
        async with session.get(f"{self.engine_url}/products") as resp:
            return await resp.json()

    async def get_capabilities(self) -> dict:
        session = await self._get_session()
        async with session.get(f"{self.engine_url}/capabilities") as resp:
            return await resp.json()

    async def get_metrics(self) -> dict:
        session = await self._get_session()
        async with session.get(f"{self.engine_url}/metrics") as resp:
            return await resp.json()

    async def get_transactions(self) -> list[dict]:
        session = await self._get_session()
        async with session.get(f"{self.engine_url}/transactions") as resp:
            return await resp.json()

    async def create_checkout(
        self, items: list[dict], protocol: str, agent_id: str
    ) -> dict:
        session = await self._get_session()
        async with session.post(
            f"{self.engine_url}/checkout_sessions",
            json={"items": items, "protocol": protocol, "agent_id": agent_id},
        ) as resp:
            return await resp.json()

    async def update_checkout(
        self,
        session_id: str,
        fulfillment_address: Optional[dict] = None,
        selected_fulfillment_option_id: Optional[str] = None,
    ) -> dict:
        session = await self._get_session()
        body: dict = {}
        if fulfillment_address:
            body["fulfillment_address"] = fulfillment_address
        if selected_fulfillment_option_id:
            body["selected_fulfillment_option_id"] = selected_fulfillment_option_id
        async with session.post(
            f"{self.engine_url}/checkout_sessions/{session_id}",
            json=body,
        ) as resp:
            return await resp.json()

    async def complete_checkout(
        self,
        session_id: str,
        payment_token: str,
        protocol: str,
        merchant: Optional[str] = None,
    ) -> dict:
        session = await self._get_session()
        body = {"payment_token": payment_token, "protocol": protocol}
        if merchant:
            body["merchant"] = merchant
        async with session.post(
            f"{self.engine_url}/checkout_sessions/{session_id}/complete",
            json=body,
        ) as resp:
            data = await resp.json()
            data["_status"] = resp.status
            return data

    async def execute_payment(
        self,
        actor_id: str,
        protocol: str,
        amount_cents: int,
        merchant: str,
        round_num: int,
        workload_type: str,
        source_domain: Optional[str] = None,
        target_domain: Optional[str] = None,
        primitive: Optional[str] = None,
        route_id: Optional[str] = None,
        margin_delta_cents: int = 0,
    ) -> TransactionRecord:
        session = await self._get_session()
        async with session.post(
            f"{self.engine_url}/payments/execute",
            json={
                "actor_id": actor_id,
                "protocol": protocol,
                "amount_cents": amount_cents,
                "merchant": merchant,
                "currency": "usd",
            },
        ) as resp:
            data = await resp.json()
            if resp.status >= 400:
                return TransactionRecord(
                    round_num=round_num,
                    agent_id=actor_id,
                    protocol=protocol,
                    product_id="",
                    product_name=workload_type,
                    amount=0,
                    fee=0,
                    settlement_ms=0,
                    success=False,
                    error=data.get("message", str(data)),
                    merchant_id=merchant,
                    merchant_name=merchant,
                    workload_type=workload_type,
                    source_domain=source_domain,
                    target_domain=target_domain,
                    primitive=primitive,
                    route_id=route_id,
                    margin_delta_cents=margin_delta_cents,
                )

            return TransactionRecord(
                round_num=round_num,
                agent_id=actor_id,
                protocol=protocol,
                product_id="",
                product_name=workload_type,
                amount=data.get("amount_cents", amount_cents),
                fee=data.get("fee_cents", 0),
                settlement_ms=data.get("execution_us", 0) / 1000.0,
                success=data.get("status", "").lower() == "settled",
                merchant_id=merchant,
                merchant_name=merchant,
                workload_type=workload_type,
                source_domain=source_domain,
                target_domain=target_domain,
                primitive=primitive,
                route_id=route_id,
                margin_delta_cents=margin_delta_cents,
            )

    async def full_purchase(
        self,
        agent_id: str,
        product_id: str,
        quantity: int,
        protocol: str,
        round_num: int,
        product_name: str = "",
        needs_shipping: bool = True,
        agent_address: Optional[dict] = None,
        merchant_id: Optional[str] = None,
        merchant_name: Optional[str] = None,
        ecosystem_pressure: float = 0.0,
        workload_type: Optional[str] = None,
        source_domain: Optional[str] = None,
        target_domain: Optional[str] = None,
        primitive: Optional[str] = None,
        route_id: Optional[str] = None,
        margin_delta_cents: int = 0,
    ) -> TransactionRecord:
        """Execute a full checkout flow and return a transaction record."""
        session_id = None
        try:
            checkout = await self.create_checkout(
                items=[{"id": product_id, "quantity": quantity}],
                protocol=protocol,
                agent_id=agent_id,
            )

            if "id" not in checkout:
                return TransactionRecord(
                    round_num=round_num,
                    agent_id=agent_id,
                    protocol=protocol,
                    product_id=product_id,
                    product_name=product_name,
                    amount=0,
                    fee=0,
                    settlement_ms=0,
                    success=False,
                    error=checkout.get("message", str(checkout)),
                    merchant_id=merchant_id,
                    merchant_name=merchant_name,
                    ecosystem_pressure=ecosystem_pressure,
                    workload_type=workload_type,
                    source_domain=source_domain,
                    target_domain=target_domain,
                    primitive=primitive,
                    route_id=route_id,
                    margin_delta_cents=margin_delta_cents,
                )

            session_id = checkout["id"]

            if needs_shipping and agent_address:
                try:
                    await self.update_checkout(
                        session_id=session_id,
                        fulfillment_address=agent_address,
                        selected_fulfillment_option_id="ship_standard",
                    )
                except Exception as exc:
                    await self._cancel_session(session_id)
                    return TransactionRecord(
                        round_num=round_num,
                        agent_id=agent_id,
                        protocol=protocol,
                        product_id=product_id,
                        product_name=product_name,
                        amount=0,
                        fee=0,
                        settlement_ms=0,
                        success=False,
                        error=f"address update failed: {exc}",
                        merchant_id=merchant_id,
                        merchant_name=merchant_name,
                        ecosystem_pressure=ecosystem_pressure,
                        workload_type=workload_type,
                        source_domain=source_domain,
                        target_domain=target_domain,
                        primitive=primitive,
                        route_id=route_id,
                        margin_delta_cents=margin_delta_cents,
                    )

            token = f"token_{protocol}_{agent_id}_{round_num}"
            result = await self.complete_checkout(
                session_id, token, protocol, merchant=merchant_id
            )

            if result.get("status") != "completed":
                return TransactionRecord(
                    round_num=round_num,
                    agent_id=agent_id,
                    protocol=protocol,
                    product_id=product_id,
                    product_name=product_name,
                    amount=0,
                    fee=0,
                    settlement_ms=0,
                    success=False,
                    error=result.get("message", "checkout failed"),
                    merchant_id=merchant_id,
                    merchant_name=merchant_name,
                    ecosystem_pressure=ecosystem_pressure,
                    workload_type=workload_type,
                    source_domain=source_domain,
                    target_domain=target_domain,
                    primitive=primitive,
                    route_id=route_id,
                    margin_delta_cents=margin_delta_cents,
                )

            total = 0
            for total_row in result.get("totals", []):
                if total_row.get("type") == "total":
                    total = total_row["amount"]

            fee = 0
            settlement_ms = 0.0
            for msg in result.get("messages", []):
                if msg.get("type") != "payment_result":
                    continue
                try:
                    payment_data = json.loads(msg["content"])
                    fee = payment_data.get("fee_cents", 0)
                    settlement_ms = payment_data.get("execution_us", 0) / 1000.0
                except (json.JSONDecodeError, KeyError):
                    proto_enum = Protocol(protocol)
                    fee = PROTOCOL_FEE_FORMULAS.get(proto_enum, lambda a: 0)(total)

            return TransactionRecord(
                round_num=round_num,
                agent_id=agent_id,
                protocol=protocol,
                product_id=product_id,
                product_name=product_name,
                amount=total,
                fee=fee,
                settlement_ms=settlement_ms,
                success=True,
                session_id=session_id,
                order_id=result.get("order", {}).get("id"),
                merchant_id=merchant_id,
                merchant_name=merchant_name,
                ecosystem_pressure=ecosystem_pressure,
                workload_type=workload_type,
                source_domain=source_domain,
                target_domain=target_domain,
                primitive=primitive,
                route_id=route_id,
                margin_delta_cents=margin_delta_cents,
            )
        except Exception as exc:
            if session_id:
                try:
                    await self._cancel_session(session_id)
                except Exception:
                    pass
            return TransactionRecord(
                round_num=round_num,
                agent_id=agent_id,
                protocol=protocol,
                product_id=product_id,
                product_name=product_name,
                amount=0,
                fee=0,
                settlement_ms=0,
                success=False,
                error=str(exc),
                merchant_id=merchant_id,
                merchant_name=merchant_name,
                ecosystem_pressure=ecosystem_pressure,
                workload_type=workload_type,
                source_domain=source_domain,
                target_domain=target_domain,
                primitive=primitive,
                route_id=route_id,
                margin_delta_cents=margin_delta_cents,
            )

    async def _cancel_session(self, session_id: str):
        session = await self._get_session()
        try:
            await session.post(
                f"{self.engine_url}/checkout_sessions/{session_id}/cancel"
            )
        except Exception:
            pass
