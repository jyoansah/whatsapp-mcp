#!/bin/bash

# WhatsApp MCP Start Script
# Runs both the Go bridge and Python MCP server with bridge auto-restart

# Bridge watchdog: restarts the Go bridge if it crashes
run_bridge() {
    while true; do
        echo "[watchdog] Starting WhatsApp bridge..."
        whatsapp-bridge
        EXIT_CODE=$?
        echo "[watchdog] WhatsApp bridge exited with code $EXIT_CODE. Restarting in 10 seconds..."
        sleep 10
    done
}

# Start bridge watchdog in background
run_bridge &
BRIDGE_PID=$!

# Wait for bridge to initialize
sleep 5

# Start MCP server in foreground
cd /app/whatsapp-mcp-server
uv run main.py &
MCP_PID=$!

# Handle shutdown: kill both processes
cleanup() {
    echo "[start.sh] Shutting down..."
    kill $BRIDGE_PID $MCP_PID 2>/dev/null
    wait $BRIDGE_PID $MCP_PID 2>/dev/null
    exit 0
}

trap cleanup SIGTERM SIGINT

# Wait for either process to exit
wait -n $BRIDGE_PID $MCP_PID
EXIT_CODE=$?

echo "[start.sh] A child process exited with code $EXIT_CODE, shutting down..."
cleanup
