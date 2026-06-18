const express = require("express");
const fetch = require("node-fetch");
const { Server } = require("@modelcontextprotocol/server");
const { StreamableHTTPServerTransport } = require("@modelcontextprotocol/server/streamable-http");

const SL_PIPELINE_URL = process.env.SL_PIPELINE_URL;
const SL_PIPELINE_TOKEN = process.env.SL_PIPELINE_TOKEN;
const MCP_API_KEY = process.env.MCP_API_KEY;
const PORT = process.env.PORT || 8000;

if (!SL_PIPELINE_URL || !SL_PIPELINE_TOKEN || !MCP_API_KEY) {
  console.error("Missing required env vars: SL_PIPELINE_URL, SL_PIPELINE_TOKEN, MCP_API_KEY");
  process.exit(1);
}

async function callPipeline(payload) {
  const res = await fetch(SL_PIPELINE_URL, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${SL_PIPELINE_TOKEN}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`SnapLogic error ${res.status}: ${text}`);
  }

  const data = await res.json();
  if (Array.isArray(data) && data.length === 1) return data[0];
  return data;
}

// Create MCP server
const server = new Server(
  {
    name: "snaplogic-agent",
    version: "1.0.0"
  },
  {
    capabilities: { tools: {} }
  }
);

// Define the single tool
server.tool("run_agent_tool", {
  description: "Invoke the SnapLogic agentic pipeline. It decides which internal tool to call (CRM, search, webpage) based on the user_message.",
  inputSchema: {
    type: "object",
    properties: {
      user_message: { type: "string", description: "User question or request." },
      conversation_history: {
        type: "array",
        description: "Optional prior turns, as [{content, sl_role}].",
        items: {
          type: "object",
          properties: {
            content: { type: "string" },
            sl_role: { type: "string" }
          }
        }
      }
    },
    required: ["user_message"]
  }
}, async ({ user_message, conversation_history }) => {
  const contents = Array.isArray(conversation_history) ? [...conversation_history] : [];
  contents.push({ content: user_message, sl_role: "USER" });

  const result = await callPipeline({ contents });
  return [
    {
      type: "text",
      text: JSON.stringify(result)
    }
  ];
});

// Set up Express + Streamable HTTP transport
const app = express();

// Health endpoint without auth
app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

// Auth middleware for MCP
app.use((req, res, next) => {
  if (req.path === "/health") return next();
  const apiKey = req.headers["x-api-key"] || (req.headers["authorization"] || "").replace(/^Bearer\s+/i, "");
  if (apiKey !== MCP_API_KEY) {
    return res.status(401).json({ error: "unauthorized" });
  }
  next();
});

const transport = new StreamableHTTPServerTransport({
  server,
  path: "/mcp",
});

transport.apply(app);

app.listen(PORT, () => {
  console.log(`MCP server listening on port ${PORT}`);
});
