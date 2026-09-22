"""MCP client.

Spawns the Yukti MCP server over stdio, discovers its tools, and invokes them.
Discovery is the point: the client does not hardcode the tool list, it asks — so
the same code works against any MCP server.
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass(frozen=True)
class DiscoveredTool:
    name: str
    description: str
    input_schema: dict[str, Any]


@asynccontextmanager
async def connect(workspace: Path) -> AsyncIterator[ClientSession]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "yukti_mcp.server", str(workspace)],
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def discover(session: ClientSession) -> list[DiscoveredTool]:
    result = await session.list_tools()
    return [
        DiscoveredTool(
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.input_schema or {},
        )
        for tool in result.tools
    ]


async def call(session: ClientSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = await session.call_tool(name, arguments)
    if structured := getattr(result, "structured_content", None):
        return dict(structured)
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            try:
                parsed: dict[str, Any] = json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
            return parsed
    return {}
