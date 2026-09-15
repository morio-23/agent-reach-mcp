import asyncio

from mcp import Client

from agent_reach_mcp.config import Settings
from agent_reach_mcp.server import create_mcp


async def main() -> None:
    mcp = create_mcp(Settings(_env_file=None))
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print("MCP protocol:", client.protocol_version)
        print("Tools:", ", ".join(tool.name for tool in tools.tools))
        result = await client.call_tool("get_capabilities", {})
        if result.is_error:
            raise SystemExit(f"get_capabilities failed: {result.content}")
        print("get_capabilities: OK")


if __name__ == "__main__":
    asyncio.run(main())
