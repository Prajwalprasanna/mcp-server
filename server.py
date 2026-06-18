import os
import json
import logging
import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route, Mount

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mcp-passthrough")

SL_PIPELINE_URL = os.environ["SL_PIPELINE_URL"]
SL_PIPELINE_TOKEN = os.environ["SL_PIPELINE_TOKEN"]
MCP_API_KEY = os.environ["MCP_API_KEY"]
PORT = int(os.getenv("PORT", "8000"))


async def call_pipeline(payload: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {SL_PIPELINE_TOKEN}",
        "Content-Type": "application/json",
    }
    log.info("Calling SnapLogic with payload keys=%s", list(payload.keys()))
    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(SL_PIPELINE_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    return data


mcp = FastMCP("snaplogic-agent")


@mcp.tool()
async def run_agent_tool(user_message: str, conversation_history: list = None) -> str:
    """Invokes the SnapLogic agentic pipeline. The pipeline will internally
    decide which tool to call (CRM lookup, web search, webpage fetch, etc.)
    and return the tool's output. Call this tool whenever you need to
    access enterprise data via SnapLogic. If the response indicates a tool
    was called but no final answer was produced, call this tool again with
    the updated conversation_history (appending the previous response) so
    the pipeline can take the next step.

    Args:
        user_message: The user's question or request to process.
        conversation_history: Optional. Previous turns in the conversation,
            as a list of {"content": str, "sl_role": "USER"|"MODEL"|"TOOL"} entries.
            Pass this back on subsequent calls to continue an in-progress
            agentic conversation.

    Returns:
        The pipeline's JSON response (as a string), containing either the
        final answer or an intermediate tool call result.
    """
    contents = conversation_history or []
    contents.append({"content": user_message, "sl_role": "USER"})

    payload = {"contents": contents}
    result = await call_pipeline(payload)
    return json.dumps(result)


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
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


async def root(_request):
    return JSONResponse({"service": "snaplogic-mcp-passthrough", "status": "ok"})


# Build the MCP sub-app (with auth middleware)
mcp_app = mcp.streamable_http_app()
mcp_app.add_middleware(ApiKeyAuthMiddleware)

# Outer app — /health and / are public; everything else goes through MCP (with auth)
app = Starlette(
    routes=[
        Route("/health", health),
        Route("/", root),
        Mount("/", app=mcp_app),
    ],
    lifespan=mcp_app.router.lifespan_context,
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        forwarded_allow_ips="*",
        proxy_headers=True,
    )
