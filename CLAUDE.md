# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

WhatsApp MCP is a Model Context Protocol server that provides Claude with access to WhatsApp messages and contacts. It consists of two components that must run together:

1. **Go Bridge** (`whatsapp-bridge/`) - Connects to WhatsApp Web API via whatsmeow library, stores messages in SQLite, exposes REST API on port 8080
2. **Python MCP Server** (`whatsapp-mcp-server/`) - FastMCP server that reads from SQLite and communicates with the Go bridge

## Commands

### Go Bridge
```bash
cd whatsapp-bridge
go build -o whatsapp-bridge  # Build
./whatsapp-bridge            # Run (first run shows QR code for WhatsApp auth)
```

### Python MCP Server
```bash
cd whatsapp-mcp-server
uv run main.py               # Run with UV package manager
```

## Architecture

```
Claude ←→ MCP Server (Python/stdio) ←→ SQLite DB ←→ Go Bridge ←→ WhatsApp
                                    ←→ REST API (localhost:8080)
```

**Data flow:**
- Go bridge maintains persistent WhatsApp connection and stores all messages/contacts in `whatsapp-bridge/store/messages.db`
- MCP server reads from SQLite for queries, calls REST API for actions (send message, download media)

**Key files:**
- `whatsapp-bridge/main.go` - WhatsApp connection, message handlers, REST API, scheduler, channel watcher
- `whatsapp-mcp-server/main.py` - MCP tool definitions (18 tools including scheduling and watching)
- `whatsapp-mcp-server/whatsapp.py` - Data access layer, SQLite queries, REST client

## Message Scheduling

The Go bridge includes a scheduler that checks for due messages every 30 seconds.

**MCP Tools:**
- `schedule_message(recipient, message, scheduled_time, media_path?)` - Schedule future message
- `list_scheduled_messages(status?)` - List scheduled messages (filter: pending/sent/failed)
- `cancel_scheduled_message(message_id)` - Cancel a pending scheduled message

**REST Endpoints:**
- `POST /api/schedule` - Create scheduled message
- `GET /api/schedule?status=pending` - List scheduled messages
- `DELETE /api/schedule?id=123` - Cancel scheduled message

**Webhook:**
- `POST /api/webhook/schedule` - External trigger (sends immediately if no scheduled_time or time is <30s away)

**Request format:**
```json
{
  "recipient": "1234567890",
  "message": "Hello!",
  "scheduled_time": "2024-12-25T10:00:00Z",
  "media_path": "/path/to/file.jpg"
}
```

## Channel Watching

Watch specific channels and receive webhook notifications when messages arrive.

**Environment variable:**
```bash
export WHATSAPP_WEBHOOK_URL="https://your-n8n-instance.com/webhook/whatsapp"
```

**MCP Tools:**
- `watch_channel(jid, name?)` - Add channel to watch list
- `unwatch_channel(jid)` - Remove channel from watch list
- `list_watched_channels()` - List watched channels and webhook URL

**REST Endpoints:**
- `POST /api/watch` - Add channel (`{"jid": "123@g.us", "name": "Group Name"}`)
- `GET /api/watch` - List watched channels
- `DELETE /api/watch?jid=123@g.us` - Remove channel

**Webhook payload (sent to WHATSAPP_WEBHOOK_URL):**
```json
{
  "event": "message",
  "timestamp": "2024-12-25T10:00:00Z",
  "chat": {"jid": "123@g.us", "name": "Group Name"},
  "message": {
    "id": "ABC123",
    "sender": "1234567890",
    "content": "Hello!",
    "is_from_me": false,
    "media_type": "",
    "filename": ""
  }
}
```

**WhatsApp Bot Commands (send to any chat from yourself):**
| Command | Action |
|---------|--------|
| `!watch` | Watch current chat |
| `!watch <jid> [name]` | Watch specific chat by JID |
| `!unwatch` | Stop watching current chat |
| `!unwatch <jid>` | Stop watching specific chat |
| `!watchlist` | List all watched channels |
| `!help` | Show available commands |

## MCP Configuration

Add to Claude Desktop config:
```json
{
  "mcpServers": {
    "whatsapp": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/whatsapp-mcp-server", "main.py"]
    }
  }
}
```

## Technical Notes

- Python 3.11+ required
- Audio messages require FFmpeg for Opus OGG conversion
- Windows builds need CGO enabled for go-sqlite3
- Go bridge must authenticate via QR code on first run (scan with WhatsApp mobile app)
- Messages DB path: `../whatsapp-bridge/store/messages.db` (relative to MCP server)
