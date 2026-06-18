import os
import logging
import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mcp-wrapper")

SL_PIPELINE_URL = os.environ["SL_PIPELINE_URL"]
SL_PIPELINE_TOKEN = os.environ["SL_PIPELINE_TOKEN"]
MCP_API_KEY = os.environ["MCP_API_KEY"]
PORT = int(os.getenv("PORT", "8000"))

mcp = FastMCP("snaplogic-mcp-wrapper")


async def call_snaplogic_pipeline(tool_name: str, arguments: dict) -> dict:
    """Invoke the SnapLogic Triggered Task with a tool name + arguments."""
    headers = {
        "Authorization": f"Bearer {SL_PIPELINE_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"tool_name": tool_name, "arguments": arguments}
    log.info("Invoking pipeline tool=%s args=%s", tool_name, arguments)
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(SL_PIPELINE_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    # Triggered Tasks usually wrap output in a single-element list
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    return data


# ----- Define each MCP tool, each forwards to the same pipeline -----
# Add/remove/edit these to match the tools your MCP Router dispatches

@mcp.tool()
async def your_first_tool(param1: str) -> dict:
    """Describe what this tool does.

    Args:
        param1: Description of param1.
    """
    return await call_snaplogic_pipeline("your_first_tool", {"param1": param1})


@mcp.tool()
async def your_second_tool(param_a: str, param_b: int) -> dict:
    """Describe what this tool does.

    Args:
        param_a: Description.
        param_b: Description.
    """
    return await call_snaplogic_pipeline(
        "your_second_tool",
        {"param_a": param_a, "param_b": param_b},
    )


# Add more @mcp.tool() functions per tool your pipeline supports.
# All of them forward to the same SnapLogic Triggered Task URL.


# ----- Auth middleware -----
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


app = mcp.streamable_http_app()
app.add_middleware(ApiKeyAuthMiddleware)


async def health(_request):
    return JSONResponse({"status": "ok"})

app.add_route("/health", health, methods=["GET"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)