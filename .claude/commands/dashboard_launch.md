Launch the RLM Live Recursive Dashboard and open it in Chrome.

## Steps

1. Load the Claude-in-Chrome MCP tools: `tabs_context_mcp`, `navigate`, `tabs_create_mcp`, and `read_page`. Use ToolSearch to fetch their schemas.

2. Start the NiceGUI dashboard server in the background:
   ```
   .venv/bin/python -m rlm_adk.dashboard
   ```

3. Create a Chrome MCP tab group (call `tabs_context_mcp` with `createIfEmpty: true`).

4. Create a new tab in the MCP group (`tabs_create_mcp`).

5. Navigate the new tab to `http://localhost:8080/live`.

6. Verify the page loaded by calling `read_page` and confirming "RLM Live Recursive Dashboard" appears in the page content.
