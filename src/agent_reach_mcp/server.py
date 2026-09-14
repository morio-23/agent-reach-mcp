import asyncio
import json

from agent_reach.config import Config
from agent_reach.core import AgentReach
from agent_reach.utils.text import scrub_url_credentials
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


SERVER_NAME = "agent-reach-mcp"


def create_server() -> Server:
    server = Server(SERVER_NAME)
    config = Config(read_only=True)
    agent_reach = AgentReach(config)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_capabilities",
                description=(
                    "Get the currently available Agent Reach capabilities and backend status."
                ),
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name != "get_capabilities":
                raise ValueError(f"Unknown tool: {name}")

            result = agent_reach.doctor_report()
            return [
                TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, indent=2),
                )
            ]
        except Exception as exc:
            return [
                TextContent(
                    type="text",
                    text=f"Error: {scrub_url_credentials(exc)}",
                )
            ]

    return server


async def _run_stdio() -> None:
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    asyncio.run(_run_stdio())


if __name__ == "__main__":
    main()
