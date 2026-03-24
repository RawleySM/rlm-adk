Launch the RLM Live Recursive Dashboard and open it in Chrome.

## Steps

1. Clean up stale Chrome MCP sockets (prevents "Browser extension is not connected"):
   ```bash
   rm -f /tmp/claude-mcp-browser-bridge-$USER/*.sock 2>/dev/null || true
   ```
   **DO NOT `pkill -f "chrome-native-host"`** — that kills the native messaging host the Chrome MCP extension is actively using, which severs the bridge and causes exit code 144. The non-zero exit also cascades: if this Bash call is dispatched in parallel with other tool calls, Claude Code cancels them all.

2. Load the Claude-in-Chrome MCP tools using ToolSearch:
   ```
   select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__computer
   ```

3. **Close any existing dashboard Chrome window.** Before killing the server, close stale browser tabs so the user doesn't see a broken UI during restart.
   - Call `tabs_context_mcp` (without `createIfEmpty`) to check for an existing tab group.
   - If tabs exist pointing at `localhost:8080`, close the window using the X11 close script:
     ```bash
     python3 .claude/skills/dashboard_launch/scripts/close_x11_window.py "RLM Live Recursive Dashboard"
     ```
     This sends a `_NET_CLOSE_WINDOW` message via libX11 (same as clicking X). Zero-install, works on X11.
   - If no tab group exists, skip this step.

4. **MUST: ALWAYS kill and restart the dashboard server.** The server does NOT hot-reload — it serves stale code until restarted. **NEVER skip this step**, even if port 8080 is already listening. Kill first, then start fresh:
   ```bash
   # IMPORTANT: Always kill existing server — it has stale code
   kill $(lsof -tiTCP:8080 -sTCP:LISTEN) 2>/dev/null || true; sleep 2
   ```
   Then start a fresh server in the background:
   ```bash
   .venv/bin/python -m rlm_adk.dashboard   # run_in_background
   ```
   Then poll for readiness (up to 15 seconds):
   ```bash
   for i in $(seq 1 15); do curl -sf http://localhost:8080/live > /dev/null 2>&1 && echo "ready" && break; sleep 1; done
   ```

5. Get the Chrome MCP tab context (call `tabs_context_mcp` with `createIfEmpty: true`). This creates a new tab group with one empty tab — use that tab's `tabId` for the next step. Do **not** create a second tab.

6. Navigate the empty tab (from step 5) to `http://localhost:8080/live`.

7. **Open DevTools** so that `read_console_messages` and `read_network_requests` MCP tools work (Chrome only buffers these when DevTools has been opened). Use the X11 key-sender script (the MCP `computer` tool's `key` action does NOT reliably deliver shortcuts to Chrome):
   ```bash
   python3 .claude/skills/dashboard_launch/scripts/send_x11_keys.py "RLM Live Recursive Dashboard" ctrl+shift+i
   ```
   This uses `XTestFakeKeyEvent` via libXtst to send the key combo directly to the Chrome window. Zero-install, works on X11.
   Then wait 2 seconds for DevTools to initialize before continuing.

8. **Position and resize the Chrome window** to the standard dashboard layout:
   ```bash
   python3 .claude/skills/dashboard_launch/scripts/position_x11_window.py "RLM Live Recursive Dashboard" 121 534 1745 2120
   ```
   This places the window at (121, 534) with size 1745x2120 using libX11. Zero-install, works on X11.

9. Wait 5 seconds (sleep) for the NiceGUI WebSocket handshake to complete.

10. Verify the page loaded by executing JavaScript (use `javascript_tool`):
   ```javascript
   JSON.stringify({
     connected: window.socket?.connected,
     handshake: window.did_handshake,
     title: document.querySelector('main')?.innerText?.substring(0, 60)
   })
   ```
   Confirm `connected: true` and `handshake: true` and title contains "RLM Live Recursive Dashboard".
   If not connected, try refreshing (navigate again) once before reporting failure.
