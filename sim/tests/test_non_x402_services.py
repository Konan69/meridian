"""Live checks for non-x402 direct service landing zones."""

from __future__ import annotations

import asyncio
import json
import os

import aiohttp
import pytest


ATXP_SERVICE_URL = "http://localhost:3010"
AP2_SERVICE_URL = "http://localhost:3040"


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
async def test_atxp_service_health_and_tools():
    healthy = await _wait_for_http(f"{ATXP_SERVICE_URL}/health")
    if not healthy:
        pytest.skip("Meridian ATXP service is not running on :3010")

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{ATXP_SERVICE_URL}/health") as resp:
            assert resp.status == 200
            health = await resp.json()
            assert health.get("service") == "meridian-atxp"

        async with session.post(
            f"{ATXP_SERVICE_URL}/mcp",
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        ) as resp:
            # Unauthenticated MCP access should trigger an OAuth challenge.
            assert resp.status == 401
            assert (
                resp.headers.get("WWW-Authenticate")
                == 'Bearer resource_metadata="http://localhost:3010/.well-known/oauth-protected-resource/mcp"'
            )

        async with session.get(
            f"{ATXP_SERVICE_URL}/mcp/.well-known/oauth-protected-resource",
        ) as resp:
            assert resp.status == 200
            metadata = await resp.json()
            assert metadata.get("resource") == "http://localhost:3010/mcp"
            assert "https://auth.atxp.ai" in metadata.get("authorization_servers", [])


@pytest.mark.asyncio
async def test_atxp_direct_transfer_route():
    healthy = await _wait_for_http(f"{ATXP_SERVICE_URL}/health")
    if not healthy:
        pytest.skip("Meridian ATXP service is not running on :3010")

    credential = os.environ.get("ATXP_TEST_DIRECT_CREDENTIAL")
    if not credential:
        pytest.skip("ATXP_TEST_DIRECT_CREDENTIAL not set for direct transfer test")

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{ATXP_SERVICE_URL}/atxp/direct-transfer",
            headers={
                "content-type": "application/json",
                "x-atxp-payment": credential,
            },
            json={
                "merchant": "direct-test",
                "amountUsd": 0.01,
                "memo": "pytest-direct-transfer",
            },
        ) as resp:
            text = await resp.text()
            assert resp.status == 200, text
            body = json.loads(text)
            assert body.get("ok") is True
            assert body.get("settledAmount") is not None
            assert body.get("txHash")


@pytest.mark.asyncio
async def test_ap2_service_health_and_flow():
    healthy = await _wait_for_http(f"{AP2_SERVICE_URL}/health")
    if not healthy:
        pytest.skip("Meridian AP2 service is not running on :3040")

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{AP2_SERVICE_URL}/health") as resp:
            assert resp.status == 200
            health = await resp.json()
            assert health.get("service") == "meridian-ap2"
            assert health.get("runtimeReady") is True

        async with session.post(
            f"{AP2_SERVICE_URL}/ap2/authorize",
            json={
                "actorId": "ap2_test_actor",
                "merchant": "ap2_test_merchant",
                "amountUsd": 1.25,
                "memo": "pytest-ap2",
                "requiresConfirmation": False,
            },
        ) as resp:
            assert resp.status == 200
            auth = await resp.json()
            assert auth.get("ok") is True
            credential = auth.get("credential")
            assert credential

        async with session.post(
            f"{AP2_SERVICE_URL}/ap2/settle",
            headers={"x-ap2-credential": credential},
            json={
                "merchant": "ap2_test_merchant",
                "amountUsd": 1.25,
                "memo": "pytest-ap2",
            },
        ) as resp:
            text = await resp.text()
            assert resp.status == 200, text
            body = json.loads(text)
            assert body.get("ok") is True
            assert body.get("paymentId")
            assert body.get("receipt")
