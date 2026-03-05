# Multi-stage build for WhatsApp MCP
FROM golang:1.25-alpine AS go-builder

# Install build dependencies for static linking
RUN apk add --no-cache gcc musl-dev sqlite-dev sqlite-static

WORKDIR /app/whatsapp-bridge
COPY whatsapp-bridge/ .

# Enable CGO for sqlite3 and build fully static binary
ENV CGO_ENABLED=1
RUN go mod download && go mod vendor

# Patch whatsmeow: make LTHash verification non-fatal
# WhatsApp servers sometimes reference value MACs from pruned snapshots, making
# LTHash verification mathematically impossible. The mutations are still valid —
# only the integrity check fails. This sed changes validateSnapshotMAC to log a
# warning instead of returning an error when the hash doesn't match.
# See: https://github.com/tulir/whatsmeow appstate/decode.go validateSnapshotMAC()
RUN sed -i 's|err = fmt.Errorf("failed to verify patch v%d: %w", currentState.Version, ErrMismatchingLTHash)|proc.Log.Warnf("LTHash mismatch for %s v%d (non-fatal, skipping verification)", name, currentState.Version)|' \
    vendor/go.mau.fi/whatsmeow/appstate/decode.go \
 && grep -q "non-fatal, skipping verification" vendor/go.mau.fi/whatsmeow/appstate/decode.go

RUN go build -mod=vendor -ldflags '-linkmode external -extldflags "-static"' -o whatsapp-bridge main.go

# Python stage
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

WORKDIR /app

# Copy Go binary
COPY --from=go-builder /app/whatsapp-bridge/whatsapp-bridge /usr/local/bin/

# Copy Python MCP server
COPY whatsapp-mcp-server/ ./whatsapp-mcp-server/

# Install Python dependencies
WORKDIR /app/whatsapp-mcp-server
RUN uv sync

# Create directories for data persistence
# The Go binary writes to /app/store (mounted volume)
# The Python code expects /app/whatsapp-bridge/store/ - create symlink
RUN mkdir -p /app/store /app/whatsapp-bridge && \
    ln -s /app/store /app/whatsapp-bridge/store

# Expose ports
EXPOSE 8000 8080

# Create startup script
WORKDIR /app
COPY whatsapp-mcp-start.sh /app/start.sh
RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]