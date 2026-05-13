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

This repo is a fork of `lharries/whatsapp-mcp`, hosted at `drapesinc/whatsapp-mcp`. It is consumed by the `server` repo as a git submodule at `whatsapp-mcp/`. Both mini and hz-dr build their containers from this submodule path — same source, same image.

When checked out via the submodule, the only remote is `origin` (drapesinc/whatsapp-mcp). Push there:

```bash
cd ${DOCKERDIR:-~/server}/whatsapp-mcp
git push origin main
```

After pushing, bump the submodule pointer in the parent `server` repo so other servers can pull the new commit:

```bash
cd ${DOCKERDIR:-~/server}
git add whatsapp-mcp
git commit -m "submodule: bump whatsapp-mcp"
git push
```

Pulling on another host:

```bash
cd ${DOCKERDIR:-~/server}
git pull
git submodule update --init whatsapp-mcp
./scripts/compose-up.sh build whatsapp-mcp
./scripts/compose-up.sh up -d whatsapp-mcp
```

If you're tracking upstream `lharries/whatsapp-mcp`, add it as a remote in your local checkout — but don't push there:

```bash
git remote add upstream https://github.com/lharries/whatsapp-mcp.git
git fetch upstream
```

The Drapes whatsmeow fork (`github.com/drapesinc/whatsmeow`) wired in via the `replace` directive in `whatsapp-bridge/go.mod` is shared by both deployments.

---

## Deployments

There are **two managed deployments** of this MCP plus a documented path for **anyone running their own**. All three use the same image built from this repo; what differs is which WhatsApp account is linked, where it runs, and how it's auth-gated.

| Deployment | Server | WhatsApp account | SSE endpoint | Media endpoint | Auth | Compose file |
|------------|--------|------------------|--------------|----------------|------|--------------|
| **Drapes business** (default for Drapes work) | hz-dr | Drapes business number | `https://whatsapp.drapesinc.com/sse` | `https://whatsapp.drapesinc.com/api/media/...` | Bearer token (`WHATSAPP_MCP_BEARER_TOKEN`) | `compose/hz/whatsapp-mcp.yml` |
| **Yaw personal** | Mac Mini | Yaw's personal number | `https://mcp.mini.jyoansah.me/whatsapp/sse` | `https://whatsapp.mini.jyoansah.me/api/media/...` | Tailnet-only DNS | `compose/mini/whatsapp-mcp.yml` |
| **Your personal** | Anywhere | Your number | Up to you | Up to you | Up to you | See "Run your own" below |

For client work, **default to the Drapes-business deployment on hz-dr.** The mini deployment is Yaw's personal account and shouldn't be the path for team or client conversations.

### Connecting Claude Code

Add to `~/.claude.json` under `mcpServers`. **Drapes business (recommended for team / client work):**

```json
"whatsapp-drapes": {
  "command": "npx",
  "args": [
    "-y", "mcp-remote",
    "https://whatsapp.drapesinc.com/sse",
    "--transport", "sse-only",
    "--header", "Authorization: Bearer ${WHATSAPP_MCP_BEARER_TOKEN}"
  ]
}
```

The bearer token is in 1Password (Drapes vault) — ask Yaw if you need it. Tools land as `mcp__whatsapp-drapes__*`.

**Yaw personal (Mini, tailnet only):**

```json
"whatsapp": {
  "command": "npx",
  "args": [
    "-y", "mcp-remote",
    "https://mcp.mini.jyoansah.me/whatsapp/sse",
    "--transport", "sse-only"
  ]
}
```

Requires Tailscale on the client machine. Tools land as `mcp__whatsapp__*`.

### Connection chain

The same image and ports run on both servers:

```
Python MCP SSE: container :8000   ← /sse (and /messages/*)
Go bridge REST: container :8080   ← /api/* (download_media, send file, etc.)
```

Traefik routes the public hostname to those internal ports. `WHATSAPP_PUBLIC_URL` tells the bridge what hostname to stamp into `download_media` responses so URLs are reachable from outside the container.

### Run your own personal instance

This repo is a fork of `lharries/whatsapp-mcp` plus a Dockerfile, watchdog start script, LTHash patch, and a few feature additions (scheduled messages, channel watcher, media REST endpoint). To run your own instance against your personal WhatsApp:

1. Clone the repo somewhere on the host that will run the container.
2. Build the image:
   ```bash
   docker build -t whatsapp-mcp -f whatsapp-mcp.Dockerfile .
   ```
3. Run it (basic stdio/SSE, no reverse proxy):
   ```bash
   docker run -d --name whatsapp-mcp \
     -e MCP_TRANSPORT=sse \
     -e WHATSAPP_PUBLIC_URL=http://<your-host-or-domain>:8080 \
     -p 8000:8000 -p 8080:8080 \
     -v whatsapp-mcp-data:/app/store \
     whatsapp-mcp
   ```
4. Watch the logs once: `docker logs -f whatsapp-mcp`. The bridge prints a QR code on first start — scan it from WhatsApp → Settings → Linked Devices.
5. Point Claude Code at `http://<your-host>:8000/sse` (or front it with your own reverse proxy + auth — `compose/hz/whatsapp-mcp.yml` is the worked example).

Things to know if you self-host:

- The bridge is your account, with full read/send privileges. Don't expose `:8000` or `:8080` to the public internet without auth in front.
- `WHATSAPP_PUBLIC_URL` must point at whatever hostname your client/agent can reach `/api/media/*` on. Without it, `download_media` returns `http://localhost:8080/...` and the agent can't fetch files.
- Persistent storage at `/app/store` holds your WhatsApp credentials. Lose the volume → re-scan the QR code.

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
2. `go mod vendor` — vendors all dependencies locally (resolves the whatsmeow `replace` directive to the Drapes fork)
3. Builds Go binary with `-mod=vendor`
4. `python:3.11-slim` — runs the MCP server with uv
5. Symlinks `/app/store` for shared SQLite access

### Environment Variables

Set in the relevant compose file (`compose/mini/whatsapp-mcp.yml` for Yaw-personal, `compose/hz/whatsapp-mcp.yml` for Drapes-business):

| Variable | Purpose |
|----------|---------|
| `MCP_TRANSPORT=sse` | MCP server uses SSE transport (not stdio) |
| `WHATSAPP_WEBHOOK_URL` | n8n webhook for watched channel notifications |
| `WHATSAPP_PUBLIC_URL` | Public base URL the bridge stamps into `download_media` responses. Without it, `public_url` comes back as `http://localhost:8080/...` and is unreachable from outside the container. Set to the hostname Traefik (or whatever proxy) routes to port 8080. |

---

## Development Workflow

### Making Go Bridge Changes

```bash
cd ${DOCKERDIR:-~/server}/whatsapp-mcp/whatsapp-bridge

# Edit main.go
# Build locally to check for compile errors:
go build -o whatsapp-bridge

# When ready, rebuild the Docker container:
cd ~/server
./scripts/compose-up.sh build whatsapp-mcp
./scripts/compose-up.sh up -d whatsapp-mcp
docker logs whatsapp-mcp --tail 20

# Commit and push from the submodule (drapesinc/whatsapp-mcp):
cd ${DOCKERDIR:-~/server}/whatsapp-mcp
git add whatsapp-bridge/
git commit -m "fix/feat: description"
git push origin main

# Then bump the submodule pointer in the parent server repo:
cd ${DOCKERDIR:-~/server}
git add whatsapp-mcp
git commit -m "submodule: bump whatsapp-mcp"
git push
```

### Making Python MCP Changes

```bash
cd ${DOCKERDIR:-~/server}/whatsapp-mcp/whatsapp-mcp-server

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

### Updating whatsmeow

`go.mod` pins `go.mau.fi/whatsmeow` to the Drapes fork via a `replace` directive (`github.com/drapesinc/whatsmeow`). The fork sits on top of upstream `tulir/whatsmeow` and adds the diverging-LTHash handling — see the LTHash section below.

To pull in upstream changes:

1. In `~/Dev/whatsmeow-fork`, fetch the latest upstream and rebase: `git fetch upstream && git rebase upstream/main`, resolve any conflicts in `appstate/decode.go`, force-push to `origin` (drapesinc).
2. Bump the require version + the replace pseudo-version in `whatsapp-bridge/go.mod` to match the new fork HEAD.
3. `go mod tidy`, rebuild the container, test.

Do NOT add `go get -u go.mau.fi/whatsmeow@latest` to the Dockerfile or to local workflow — it would clobber the replace directive and lose the LTHash fix silently.

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

## LTHash Diverging-Hash Handling (via Drapes whatsmeow fork)

### What It Is

WhatsApp syncs settings (archive, pin, mute, star) across devices using "app state" with LTHash rolling integrity verification. The Drapes fork of whatsmeow (`github.com/drapesinc/whatsmeow`, wired in via `replace` in `go.mod`) changes the patch-decode loop so a diverged LTHash logs a warning and skips verification for that patch instead of aborting.

### Why It's Needed

WhatsApp's servers sometimes send REMOVE operations that reference value MACs from snapshots that have been compacted/pruned. Without the previous value MAC, the rolling hash can't be computed correctly, making verification mathematically impossible. Without this handling, archive/pin/mute/star operations break permanently the moment a sync gap shows up.

### How It Works

The fork rewrites the `validatePatch` and snapshot-decode code paths in `appstate/decode.go`:

- When LTHash diverges *and* there are missing value MACs (warn > 0), the divergence is attributable to the pruned snapshot. Log and continue.
- When LTHash diverges *without* missing MACs, the state is permanently desynced. Log and continue (still safer to proceed than to wedge forever).
- The patchMAC check (a separate integrity check) only runs when LTHash agrees and there are no missing MACs, so corrupt patches still get rejected.

The fork's commits live on `main` in `github.com/drapesinc/whatsmeow` and are rebased on top of upstream `tulir/whatsmeow` whenever upstream is pulled forward.

### If Upstream Changes the Surrounding Code

A rebase conflict in `appstate/decode.go` is the canonical signal that upstream has touched the patch validation path (e.g., the 2026-04 constant-time-comparison change). Resolve in `~/Dev/whatsmeow-fork`, keep the fork's `if err == nil && len(warn) == 0` guard around any new patchMAC check, then force-push.

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
