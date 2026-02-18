# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

WhatsApp MCP is a Model Context Protocol server that provides Claude with access to WhatsApp messages and contacts. It consists of two components that must run together:

1. **Go Bridge** (`whatsapp-bridge/`) - Connects to WhatsApp Web API via whatsmeow library, stores messages in SQLite, exposes REST API on port 8080
2. **Python MCP Server** (`whatsapp-mcp-server/`) - FastMCP server that reads from SQLite and communicates with the Go bridge

## Architecture

```
                         ┌─────────────────────────────────────────────┐
                         │           Docker Container                  │
Claude Desktop ──SSE──→  │  Python MCP Server (:8000)                  │
                         │       ↕ SQLite        ↕ REST API            │
Claude Code ────SSE──→   │  Go Bridge (:8080) ←──→ WhatsApp Web API   │
                         │       ↓                                     │
                         │  store/messages.db  store/whatsapp.db       │
                         └─────────────────────────────────────────────┘
                                        ↑ volume mount
                              ${DOCKERDIR}/whatsapp-mcp-data
```

**Data flow:**
- Go bridge maintains persistent WhatsApp connection and stores all messages/contacts in SQLite
- MCP server reads from SQLite for queries, calls REST API for actions (send, archive, etc.)
- Both components share the `/app/store` volume

**Key files:**
- `whatsapp-bridge/main.go` - WhatsApp connection, message handlers, REST API, scheduler, channel watcher
- `whatsapp-mcp-server/main.py` - MCP tool definitions (20 tools)
- `whatsapp-mcp-server/whatsapp.py` - Data access layer, SQLite queries, REST client

## Repositories and Remotes

This is a fork of `lharries/whatsapp-mcp`. You don't have write access to origin.

```bash
origin  https://github.com/lharries/whatsapp-mcp.git   # upstream, read-only
fork    git@github.com:jyoansah/whatsapp-mcp.git        # our fork, push here
```

**Always push to `fork`, not `origin`:**
```bash
git push fork main
```

---

## Deployment

### How It Runs

The WhatsApp MCP runs as a Docker container on the Mac Mini, built from `/Users/serveradmin/server/whatsapp-mcp.Dockerfile`. The container runs both the Go bridge and Python MCP server via a watchdog start script.

### Connection Chain (Claude → WhatsApp)

```
Claude Desktop/Code
  → mcp-remote (npx)
    → https://mcp.mini.jyoansah.me/whatsapp/sse
      → Tailscale (100.115.204.81:443)
        → Tailscale Serve → 127.0.0.1:8443
          → SSH tunnel → Colima VM:443
            → Traefik (strips /whatsapp prefix)
              → whatsapp-mcp container:8000 (Python MCP SSE)
                → localhost:8080 (Go Bridge REST API)
                  → WhatsApp Web API
```

### Network Routing

| Domain | Port | Target |
|--------|------|--------|
| `mcp.mini.jyoansah.me/whatsapp/*` | 8000 | MCP SSE (Python) — prefix stripped by Traefik |
| `whatsapp.mini.jyoansah.me/*` | 8080 | REST API (Go bridge) — direct |

### Build and Deploy

```bash
cd ~/server

# Build the container image
./scripts/compose-up.sh build whatsapp-mcp

# Deploy (recreate container with new image)
./scripts/compose-up.sh up -d whatsapp-mcp

# Verify startup
docker logs whatsapp-mcp --tail 20
# Should show: "Successfully authenticated", "Connected to WhatsApp", "Uvicorn running"
```

### What the Dockerfile Does

1. `golang:1.25-alpine` — builds the Go bridge as a static binary
2. `go mod vendor` — vendors all dependencies locally
3. `sed` patch — makes LTHash verification non-fatal (see LTHash section below)
4. Builds Go binary with `-mod=vendor`
5. `python:3.11-slim` — runs the MCP server with uv
6. Symlinks `/app/store` for shared SQLite access

### Environment Variables

Set in `compose/mini/whatsapp-mcp.yml`:

| Variable | Purpose |
|----------|---------|
| `MCP_TRANSPORT=sse` | MCP server uses SSE transport (not stdio) |
| `WHATSAPP_WEBHOOK_URL` | n8n webhook for watched channel notifications |

---

## Development Workflow

### Making Go Bridge Changes

```bash
cd /Users/serveradmin/Dev/whatsapp-mcp/whatsapp-bridge

# Edit main.go
# Build locally to check for compile errors:
go build -o whatsapp-bridge

# When ready, rebuild the Docker container:
cd ~/server
./scripts/compose-up.sh build whatsapp-mcp
./scripts/compose-up.sh up -d whatsapp-mcp
docker logs whatsapp-mcp --tail 20

# Commit and push:
cd /Users/serveradmin/Dev/whatsapp-mcp
git add whatsapp-bridge/
git commit -m "fix/feat: description"
git push fork main
```

### Making Python MCP Changes

```bash
cd /Users/serveradmin/Dev/whatsapp-mcp/whatsapp-mcp-server

# Edit main.py or whatsapp.py
# Test locally (requires bridge running):
uv run main.py

# Rebuild and deploy same as above
```

### Adding New Dependencies

**Go:**
```bash
cd whatsapp-bridge
go get <package>
# go.mod and go.sum update automatically
# Rebuild Docker container (it runs go mod vendor internally)
```

**Python:**
```bash
cd whatsapp-mcp-server
uv add <package>
# pyproject.toml and uv.lock update
# Rebuild Docker container
```

### IMPORTANT: Never auto-update whatsmeow

Do NOT add `go get -u go.mau.fi/whatsmeow@latest` to the Dockerfile or run it before building. The Dockerfile applies a build-time patch to the vendored whatsmeow source. Auto-updating would vendor a different version that the sed patch might not match, silently breaking the LTHash fix.

To update whatsmeow intentionally:
1. Update the version in `go.mod`
2. Run `go mod tidy`
3. Verify the sed target string still exists in the new version
4. Rebuild and test

---

## Restart and Reconnect Procedures

### Restarting the Container

```bash
cd ~/server
./scripts/compose-up.sh restart whatsapp-mcp

# Or rebuild + restart:
./scripts/compose-up.sh build whatsapp-mcp
./scripts/compose-up.sh up -d whatsapp-mcp
```

The bridge auto-reconnects to WhatsApp on container restart (credentials stored in the persistent volume at `${DOCKERDIR}/whatsapp-mcp-data/whatsapp.db`). No QR code needed after first auth.

### Reconnecting Claude Code to WhatsApp MCP

If Claude Code reports "Failed to reconnect to whatsapp":

1. **Check if the container is running:**
   ```bash
   docker ps | grep whatsapp-mcp
   docker logs whatsapp-mcp --tail 10
   ```

2. **Check if the SSE endpoint is reachable:**
   ```bash
   curl -sN --max-time 5 https://mcp.mini.jyoansah.me/whatsapp/sse
   # Should return: event: endpoint, data: /messages/?session_id=...
   ```

3. **If SSE fails — check the connection chain:**
   ```bash
   # Gateway healthy?
   curl -s https://mcp.mini.jyoansah.me/health

   # Colima running?
   colima list

   # Port forwarding active?
   nc -z 127.0.0.1 8443 && echo "OK" || echo "BROKEN"
   ```

4. **If port forwarding is broken** (most common after Colima restart):
   ```bash
   # Re-establish SSH tunnels
   SSH_PORT=$(cat ~/.colima/_lima/colima/ssh.port 2>/dev/null || grep "Port " ~/.colima/ssh_config | awk '{print $2}')
   ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
       -i ~/.colima/_lima/_config/user -p "$SSH_PORT" \
       -L 0.0.0.0:8443:0.0.0.0:443 \
       -L 0.0.0.0:8880:0.0.0.0:80 \
       -L 0.0.0.0:18080:0.0.0.0:8080 \
       -N -f serveradmin@127.0.0.1
   ```

5. **If Colima is broken** (`colima list` shows Running but `docker ps` fails):
   ```bash
   colima stop && colima start
   # Then re-establish port forwarding (step 4)
   ```

6. **After fixing infrastructure**, restart the Claude session (`/exit` then reopen) to pick up the MCP connection.

### First-Time Setup / QR Code Auth

If the WhatsApp session is lost (e.g., logged out from phone, fresh container with empty volume):

```bash
# The bridge prints a QR code to stdout on first auth
docker logs -f whatsapp-mcp
# Scan the QR code with WhatsApp mobile → Linked Devices → Link a Device
# After successful scan, credentials persist in the volume
```

---

## LTHash Build-Time Patch

### What It Is

WhatsApp syncs settings (archive, pin, mute, star) across devices using "app state" with LTHash rolling integrity verification. The Dockerfile applies a one-line `sed` patch to whatsmeow's `appstate/decode.go` that changes `validateSnapshotMAC()` to log LTHash mismatches as warnings instead of returning errors.

### Why It's Needed

WhatsApp's servers sometimes send REMOVE operations that reference value MACs from snapshots that have been compacted/pruned. Without the previous value MAC, the rolling hash can't be computed correctly, making verification mathematically impossible. This causes permanent failures for archive/pin/mute/star operations.

### How It Works

```
# In the Dockerfile, after go mod vendor:
sed -i 's|err = fmt.Errorf("failed to verify patch v%d: %w", currentState.Version, ErrMismatchingLTHash)|proc.Log.Warnf("LTHash mismatch for %s v%d (non-fatal, skipping verification)", name, currentState.Version)|' \
    vendor/go.mau.fi/whatsmeow/appstate/decode.go
```

This changes one line in `validateSnapshotMAC()`:
- **Before:** Returns error → caller aborts → archive/pin/mute permanently broken
- **After:** Logs warning → caller continues → mutations processed normally

Key lookup failures still propagate as errors (only LTHash mismatches are skipped). The patchMAC integrity check (separate from LTHash) still runs when it can.

### If the Patch Breaks After a whatsmeow Update

The Dockerfile has a `grep -q` verification step that fails the build if the sed didn't match. If whatsmeow refactors `validateSnapshotMAC`, the build will fail clearly. To fix:

1. Check the new version's `appstate/decode.go` for the equivalent error string
2. Update the sed pattern in the Dockerfile
3. Rebuild

---

## Troubleshooting

### Container won't start
```bash
docker logs whatsapp-mcp --tail 50
```
Common causes: QR auth expired, SQLite corruption, port conflict.

### Messages not being stored
Check the bridge is connected:
```bash
docker logs whatsapp-mcp --tail 5
# Should show recent message activity, not errors
```

### Archive/pin/mute not working
```bash
# Force resync app state:
curl -X POST https://whatsapp.mini.jyoansah.me/api/resync-state \
  -H "Content-Type: application/json" -d '{"force": true}'
```

### Media download fails
The bridge needs to be connected at the time of download (media URLs expire). Recent messages work; old ones may not.

### "client outdated" errors
Update whatsmeow version in `go.mod`, rebuild container. WhatsApp periodically requires newer client versions.

---

## Commands (Local Development)

### Go Bridge
```bash
cd whatsapp-bridge
go build -o whatsapp-bridge  # Build
./whatsapp-bridge            # Run (first run shows QR code)
```

### Python MCP Server
```bash
cd whatsapp-mcp-server
uv run main.py               # Run with UV
```

## MCP Tools Reference

### Messages
- `list_messages(chat_jid, limit?)` - Read chat history
- `send_message(recipient, message)` - Send text message
- `send_reply(recipient, message, reply_to_id, reply_to_jid)` - Reply to a message
- `send_file(recipient, file_path, caption?)` - Send file/image
- `send_audio_message(recipient, audio_path)` - Send audio as voice note
- `get_message_context(chat_jid, message_id)` - Get surrounding messages
- `download_media(message_id, chat_jid)` - Download media attachment

### Contacts and Chats
- `search_contacts(query)` - Find contacts by name/number
- `list_chats(archived?)` - List conversations (filter by archived status)
- `get_direct_chat_by_contact(phone)` - Get chat with specific contact

### Chat Management
- `archive_chat(jid, archive?)` - Archive/unarchive a chat
- `resync_app_state(names?)` - Force app state resync

### Groups
- `get_group_info(group_jid)` - Group info and member list
- `add_group_member(group_jid, participant)` - Add member
- `remove_group_member(group_jid, participant)` - Remove member

### Scheduling
- `schedule_message(recipient, message, scheduled_time, media_path?)` - Schedule future message
- `list_scheduled_messages(status?)` - List scheduled (pending/sent/failed)
- `cancel_scheduled_message(message_id)` - Cancel pending message

### Channel Watching
- `watch_channel(jid, name?)` - Watch for new messages (triggers webhook)
- `unwatch_channel(jid)` - Stop watching
- `list_watched_channels()` - List watched channels

## REST API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/send` | Send message (with optional reply, media) |
| POST | `/api/schedule` | Create scheduled message |
| GET | `/api/schedule?status=pending` | List scheduled messages |
| DELETE | `/api/schedule?id=123` | Cancel scheduled message |
| POST | `/api/webhook/schedule` | External trigger for scheduled send |
| POST | `/api/archive` | Archive/unarchive chat |
| POST | `/api/resync-state` | Force app state resync |
| POST | `/api/watch` | Add channel to watch list |
| GET | `/api/watch` | List watched channels |
| DELETE | `/api/watch?jid=...` | Remove from watch list |
| GET | `/api/group?jid=...` | Get group info |
| POST | `/api/group/members` | Add group members |
| DELETE | `/api/group/members` | Remove group members |
| POST | `/api/download` | Download media |
| GET | `/api/media/<jid>/<file>` | Serve downloaded media |

## Contact Name Resolution

Priority order:
1. **whatsmeow contacts table** (`whatsapp.db`) - `full_name`, `push_name`, `business_name`
2. **chats table** (`messages.db`) - chat names stored by bridge
3. **Phone number fallback** - JID phone number

Contact lookups are cached in memory.

## Technical Notes

- Python 3.11+ required
- Go 1.25+ required (for whatsmeow dependencies)
- Audio messages require FFmpeg for Opus OGG conversion
- Messages DB: `store/messages.db`
- WhatsApp DB: `store/whatsapp.db` (whatsmeow credentials and contacts)
- Media files: `store/<chat_jid>/<filename>`
