import pytest
from sim.commerce import CommerceClient


@pytest.fixture
def client():
    return CommerceClient("http://localhost:4080")
