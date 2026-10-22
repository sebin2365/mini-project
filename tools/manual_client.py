"""규정조회 에이전트가 MCP 서버(mcp_server/safety_server.py)에 접속할 때 쓰는 클라이언트.

서버(server.py)가 켜질 때 MCP 서버 프로세스를 딱 1번 띄워 연결해 두고(start),
요청이 올 때마다 그 연결을 재사용한다. 서버가 꺼질 때 같이 끈다(stop).
"""
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "mcp_server" / "safety_server.py"


class ManualClient:
    def __init__(self):
        self._stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None

    async def start(self):
        # MCP 서버를 별도 프로세스(stdio)로 띄우고 연결한다
        self._stack = AsyncExitStack()
        params = StdioServerParameters(command=sys.executable, args=[str(SERVER_SCRIPT)],
                                       env={**os.environ, "FASTMCP_LOG_LEVEL": "ERROR"})
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

    async def stop(self):
        if self._stack:
            await self._stack.aclose()

    async def _call(self, tool: str, args: dict) -> list[dict]:
        result = await self.session.call_tool(tool, args)
        # MCP 도구의 결과는 글자(JSON 문자열)로 온다 → 파이썬 리스트로 바꾼다
        if not result.content:
            return []
        return json.loads(result.content[0].text)

    async def search(self, query: str, top_k: int = 3) -> list[dict]:
        return await self._call("search_manuals", {"query": query, "top_k": top_k})

    async def list(self) -> list[dict]:
        return await self._call("list_manuals", {})
