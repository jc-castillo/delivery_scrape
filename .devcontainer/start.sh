#!/usr/bin/env bash
# =============================================================================
# Start a shell in the delivery_scrape development container
# Usage: .devcontainer/start.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="delivery-scrape-sandbox"

# Build and start the container if it's not already running
if ! docker compose -f "$SCRIPT_DIR/docker-compose.yml" ps --status running "$SERVICE" 2>/dev/null | grep -q "$SERVICE"; then
    "$SCRIPT_DIR/build.sh"
fi

# Drop into a shell inside the container
echo "Entering container... (run 'claude --dangerously-skip-permissions' to start Claude Code)"
docker compose -f "$SCRIPT_DIR/docker-compose.yml" exec "$SERVICE" zsh
