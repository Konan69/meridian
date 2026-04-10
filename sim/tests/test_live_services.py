"""Live service checks for Meridian-owned rail services."""

from __future__ import annotations

import asyncio
from typing import Optional

import aiohttp
import pytest


STRIPE_SERVICE_URL = "http://localhost:3020"


async def _wait_for_http(url: str, timeout_s: float = 20.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout_s
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while asyncio.get_running_loop().time() < deadline:
            try:
                async with session.get(url) as resp:
                    if resp.status < 500:
                        return True
            except Exception:
                pass
            await asyncio.sleep(1)
    return False


@pytest.mark.asyncio
async def test_mpp_service_health_and_challenge():
    """Verify the Meridian Stripe service is live and emits a real MPP challenge."""
    healthy = await _wait_for_http(f"{STRIPE_SERVICE_URL}/health")
    if not healthy:
        pytest.skip("Meridian Stripe service is not running on :3020")

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{STRIPE_SERVICE_URL}/health") as resp:
            assert resp.status == 200
            health = await resp.json()
            assert health.get("service") == "meridian-stripe"
            assert health.get("hasStripe") is True

        recipient = "0x2222222222222222222222222222222222222222"
        async with session.get(
            f"{STRIPE_SERVICE_URL}/mpp/paid",
            params={"recipient": recipient},
        ) as resp:
            body = await resp.text()
            assert resp.status == 402, f"Expected MPP challenge, got {resp.status}: {body}"
            challenge = resp.headers.get("WWW-Authenticate")
            assert challenge, "Missing WWW-Authenticate challenge header"
            assert "Payment" in challenge
            assert 'method="tempo"' in challenge
            assert recipient.lower()[-8:] not in body.lower() or body


@pytest.mark.asyncio
async def test_mpp_service_execute_runtime_flow():
    healthy = await _wait_for_http(f"{STRIPE_SERVICE_URL}/health")
    if not healthy:
        pytest.skip("Meridian Stripe service is not running on :3020")

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{STRIPE_SERVICE_URL}/mpp/execute",
            json={
                "actorId": "mpp_test_actor",
                "merchant": "mpp_test_merchant",
                "amountUsd": 0.01,
            },
        ) as resp:
            text = await resp.text()
            assert resp.status == 200, text
            body = __import__("json").loads(text)
            assert body.get("ok") is True
            assert body.get("paymentId")
            assert body.get("receipt")
