import argparse
import asyncio

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def run(url: str, token: str | None) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx2.AsyncClient(headers=headers) as http_client:
        transport = streamable_http_client(url=url, http_client=http_client)
        async with Client(transport) as client:
            tools = await client.list_tools()
            print("MCP protocol:", client.protocol_version)
            print("Tools:", ", ".join(tool.name for tool in tools.tools))
            result = await client.call_tool("get_capabilities", {})
            if result.is_error:
                raise SystemExit(f"get_capabilities failed: {result.content}")
            print("get_capabilities: OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test a running agent-reach-mcp HTTP endpoint")
    parser.add_argument("--url", default="http://127.0.0.1:8080/mcp")
    parser.add_argument("--token")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.token))


if __name__ == "__main__":
    main()
