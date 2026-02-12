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
- `whatsapp-mcp-server/main.py` - MCP tool definitions (20 tools including scheduling, watching, replies, and archiving)
- `whatsapp-mcp-server/whatsapp.py` - Data access layer, SQLite queries, REST client

## Message Replies

Messages include reply context when they are replies to other messages. When viewing messages, reply information is displayed inline.

**MCP Tools:**
- `send_reply(recipient, message, reply_to_id, reply_to_jid)` - Send a message as a reply to a specific message

**Message fields for replies:**
- `reply_to_id` - ID of the message being replied to
- `reply_to_sender` - JID of the sender of the original message
- `reply_to_content` - Content snippet of the original message (truncated to 100 chars)

**REST Endpoint:**
- `POST /api/send` - Send message with optional reply support

**Request format (with reply):**
```json
{
  "recipient": "1234567890@s.whatsapp.net",
  "message": "This is my reply!",
  "reply_to_id": "ABC123DEF456",
  "reply_to_jid": "9876543210@s.whatsapp.net"
}
```

**How to get reply parameters:**
1. Use `list_messages()` or `get_message_context()` to find the message you want to reply to
2. Extract the message's `id` field for `reply_to_id`
3. Extract the message's `sender` field and append `@s.whatsapp.net` for `reply_to_jid`
4. Use the chat's `jid` as the `recipient`

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

## Chat Archiving

Archive or unarchive WhatsApp chats to hide them from the main chat list.

**MCP Tools:**
- `archive_chat(jid, archive=True)` - Archive or unarchive a chat
- `list_chats(archived=False)` - List only unarchived chats (inbox)
- `list_chats(archived=True)` - List only archived chats
- `list_chats()` - List all chats (default, no filter)

**REST Endpoint:**
- `POST /api/archive` - Archive or unarchive a chat

**Request format:**
```json
{
  "jid": "1234567890@s.whatsapp.net",
  "archive": true
}
```

**Response format:**
```json
{
  "success": true,
  "message": "Chat archived successfully",
  "jid": "1234567890@s.whatsapp.net",
  "archive": true
}
```

**Note:** Archiving a chat will automatically unpin it if it was pinned. The archived status is tracked locally in the database, so it reflects the state when chats were archived/unarchived via this MCP. Chats archived directly in the WhatsApp app won't be reflected until you archive/unarchive them via this MCP.

**LTHash Desync Handling:** The archive handler automatically detects 409 conflict / LTHash mismatch errors (caused by app state desync with WhatsApp servers) and performs a full resync of the `regular_low` app state before retrying. If archiving still fails after automatic resync, use `resync_app_state()` to manually force a full state reset.

## App State Resync

Force a full resync of WhatsApp app state when operations like archive, pin, mute, or star fail with 409/LTHash errors.

**MCP Tools:**
- `resync_app_state(names?)` - Resync specific or default app states

**REST Endpoint:**
- `POST /api/resync-state` - Force app state resync

**Request format (optional body):**
```json
{
  "names": ["regular_low", "regular_high"]
}
```
Valid state names: `regular_low` (archive/pin), `regular_high` (mute/star), `regular`, `critical_block`, `critical_unblock_low`. If no names provided, resyncs `regular_low` and `regular_high`.

**Response format:**
```json
{
  "success": true,
  "message": "Resynced 2 app state(s)",
  "results": [
    {"name": "regular_low", "success": true},
    {"name": "regular_high", "success": true}
  ]
}
```

## Group Member Management

Manage members in WhatsApp groups. You must be an admin of the group to add or remove members.

**MCP Tools:**
- `get_group_info(group_jid)` - Get group information including member list
- `add_group_member(group_jid, participant)` - Add a contact to a group
- `remove_group_member(group_jid, participant)` - Remove a contact from a group

**REST Endpoints:**
- `GET /api/group?jid=<group_jid>` - Get group info and members
- `POST /api/group/members` - Add members to a group
- `DELETE /api/group/members` - Remove members from a group

**Get Group Info Request:**
```
GET /api/group?jid=123456789@g.us
```

**Get Group Info Response:**
```json
{
  "success": true,
  "jid": "123456789@g.us",
  "name": "My Group",
  "topic": "Group description",
  "owner_jid": "1234567890@s.whatsapp.net",
  "created_at": "2024-01-01T00:00:00Z",
  "participants": [
    {
      "jid": "1234567890@s.whatsapp.net",
      "name": "John Doe",
      "is_admin": true,
      "is_super_admin": true
    },
    {
      "jid": "0987654321@s.whatsapp.net",
      "name": "Jane Smith",
      "is_admin": false,
      "is_super_admin": false
    }
  ],
  "participant_count": 2
}
```

**Add/Remove Members Request:**
```json
{
  "group_jid": "123456789@g.us",
  "participants": ["1234567890", "0987654321@s.whatsapp.net"]
}
```
Note: Participants can be provided as phone numbers (country code, no + or symbols) or full JIDs.

**Add/Remove Members Response:**
```json
{
  "success": true,
  "message": "Processed 2 participant(s)",
  "group_jid": "123456789@g.us",
  "results": [
    {"jid": "1234567890@s.whatsapp.net", "error": ""},
    {"jid": "0987654321@s.whatsapp.net", "error": ""}
  ]
}
```

**Note:** You must be an admin of the group to add or remove members. Some participants may require approval to join (WhatsApp privacy settings).

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

## Media Download

Downloaded media files are stored in `whatsapp-bridge/store/<chat_jid>/` and can be accessed via:

1. **Local file path** - Returned in the `path` field (useful when running locally)
2. **Public URL** - Returned in the `public_url` field (useful when running in Docker or remotely)

**Environment Variable:**
```bash
export WHATSAPP_PUBLIC_URL="https://mcp.mini.jyoansah.me"
```

When set, the bridge will return a `public_url` that can be accessed externally. Without this variable, the URL defaults to `http://localhost:8080`.

**MCP Tool:**
- `download_media(message_id, chat_jid)` - Download media and get access URLs

**REST Endpoints:**
- `POST /api/download` - Download media, returns path and URL
- `GET /api/media/<chat_jid>/<filename>` - Serve downloaded media file

**Response format:**
```json
{
  "success": true,
  "message": "Successfully downloaded image media",
  "filename": "image_20240101_120000.jpg",
  "path": "/app/store/1234567890@s.whatsapp.net/image_20240101_120000.jpg",
  "public_url": "https://mcp.mini.jyoansah.me/api/media/1234567890@s.whatsapp.net/image_20240101_120000.jpg",
  "media_type": "image",
  "access_note": "Media is accessible at the public_url. You can fetch it directly using: curl 'https://mcp.mini.jyoansah.me/api/media/...'"
}
```

The `public_url` is the full URL for external access. The `access_note` provides instructions for how to retrieve the media file.

## Sending Files

The `send_file` and `send_audio_message` MCP tools support both local file paths and remote URLs:

**Local file paths:**
- The Go bridge reads files directly from the local filesystem
- Example: `/Users/john/Documents/image.png`

**Remote URLs:**
- The Go bridge downloads and sends files from HTTP/HTTPS URLs
- Example: `https://example.com/photo.jpg`

**REST API format:**
```json
{
  "recipient": "1234567890@s.whatsapp.net",
  "message": "Optional caption",
  "media_path": "/local/path/to/file.jpg",
  "media_url": "https://example.com/file.jpg",
  "media_data": "base64encodeddata...",
  "filename": "custom_filename.jpg"
}
```

Priority: `media_data` > `media_url` > `media_path` (first non-empty wins)

## Technical Notes

- Python 3.11+ required
- Audio messages require FFmpeg for Opus OGG conversion
- Windows builds need CGO enabled for go-sqlite3
- Go bridge must authenticate via QR code on first run (scan with WhatsApp mobile app)
- Messages DB path: `../whatsapp-bridge/store/messages.db` (relative to MCP server)
- WhatsApp contacts DB path: `../whatsapp-bridge/store/whatsapp.db` (whatsmeow stores contacts here)

## Contact Name Resolution

The MCP server resolves contact names in this priority order:
1. **whatsmeow contacts table** (`whatsapp.db`) - Contains `full_name`, `push_name`, and `business_name` synced from WhatsApp
2. **chats table** (`messages.db`) - Contains chat names stored by the Go bridge
3. **Phone number fallback** - If no name found, displays the phone number from the JID

Contact name lookups are cached in memory to avoid repeated database queries.
