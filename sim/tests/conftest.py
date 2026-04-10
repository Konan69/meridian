import pytest_asyncio
from sim.commerce import CommerceClient


@pytest_asyncio.fixture
async def client():
    client = CommerceClient("http://localhost:4080")
    try:
        yield client
    finally:
        await client.close()
