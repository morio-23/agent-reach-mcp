import pytest
from agent_reach_mcp.auth import StaticTokenVerifier

@pytest.mark.asyncio
async def test_static_token_verifier() -> None:
    verifier = StaticTokenVerifier("secret", "http://127.0.0.1:8080/mcp")
    assert await verifier.verify_token("wrong") is None
    token = await verifier.verify_token("secret")
    assert token is not None
    assert token.client_id == "static-token-client"
    assert token.resource == "http://127.0.0.1:8080/mcp"
