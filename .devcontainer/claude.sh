#!/usr/bin/env bash
# =============================================================================
# Run Claude Code inside the delivery_scrape development container
# Usage: .devcontainer/claude.sh [claude args...]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="delivery-scrape-sandbox"

# Build and start the container if it's not already running
if ! docker compose -f "$SCRIPT_DIR/docker-compose.yml" ps --status running "$SERVICE" 2>/dev/null | grep -q "$SERVICE"; then
    "$SCRIPT_DIR/build.sh"
fi

docker compose -f "$SCRIPT_DIR/docker-compose.yml" exec "$SERVICE" claude --dangerously-skip-permissions "$@"
