import os
import logging
import asyncio
import httpx
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.streamable_http import streamable_http_server
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mcp-passthrough")

SL_PIPELINE_URL = os.environ["SL_PIPELINE_URL"]
SL_PIPELINE_TOKEN = os.environ["SL_PIPELINE_TOKEN"]
MCP_API_KEY = os.environ["MCP_API_KEY"]
PORT = int(os.getenv("PORT", "8000"))

# Cache the tool list so we don't hammer SnapLogic on every tools/list call
_tool_list_cache: list[dict] | None = None
_tool_list_lock = asyncio.Lock()


async def call_pipeline(payload: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {SL_PIPELINE_TOKEN}",
        "Content-Type": "application/json",
    }
    log.info("→ SnapLogic payload=%s", payload)
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(SL_PIPELINE_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    log.info("← SnapLogic response keys=%s", list(data.keys()) if isinstance(data, dict) else type(data))
    return data


async def fetch_tools_from_snaplogic() -> list[dict]:
    """Ask the pipeline for its tool list."""
    global _tool_list_cache
    async with _tool_list_lock:
        if _tool_list_cache is None:
            result = await call_pipeline({"action": "list_tools"})
            # Pipeline should return {"tools": [...]}
            _tool_list_cache = result.get("tools", [])
        return _tool_list_cache


# ---------- Build the MCP server ----------
server = Server("snaplogic-passthrough")


@server.list_tools()
async def list_tools() -> list[Tool]:
    tools_data = await fetch_tools_from_snaplogic()
    return [
        Tool(
            name=t["name"],
            description=t.get("description", ""),
            inputSchema=t.get("inputSchema", {"type": "object", "properties": {}}),
        )
        for t in tools_data
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    result = await call_pipeline({
        "action": "call_tool",
        "name": name,
        "arguments": arguments,
    })
    # Wrap the result as MCP text content (JSON-stringified)
    import json
    return [TextContent(type="text", text=json.dumps(result))]


# ---------- HTTP transport wiring ----------
class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in ("/health", "/"):
            return await call_next(request)
        provided = request.headers.get("x-api-key") or ""
        if not provided:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                provided = auth.split(" ", 1)[1]
        if provided != MCP_API_KEY:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


async def health(_request):
    return JSONResponse({"status": "ok"})


# Use FastMCP for simpler HTTP wiring (it's part of the same SDK)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("snaplogic-passthrough")


@mcp.tool()
async def _placeholder():
    """Placeholder — real tools come from list_tools handler below."""
    pass


# Override the tool registry with our dynamic version
# (FastMCP exposes the underlying Server via mcp._mcp_server)
mcp._mcp_server.list_tools()(list_tools)
mcp._mcp_server.call_tool()(call_tool)

app = mcp.streamable_http_app()
app.add_middleware(ApiKeyAuthMiddleware)
app.routes.append(Route("/health", health))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)