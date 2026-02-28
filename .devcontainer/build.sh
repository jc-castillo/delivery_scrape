#!/usr/bin/env bash
# =============================================================================
# Build and start the delivery_scrape development container
# Usage: .devcontainer/build.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Check for GitHub token
if [[ -z "${GH_TOKEN:-}" ]] && ! grep -q GH_TOKEN .env 2>/dev/null; then
    echo "GH_TOKEN is not set."
    echo ""
    echo "Create a fine-grained token at: https://github.com/settings/tokens?type=beta"
    echo "  - Scope it to ONLY the delivery_scrape repository"
    echo "  - Permissions: Contents (read/write), Pull requests (read/write)"
    echo ""
    echo "Then add it to .env in the project root:"
    echo "  echo 'GH_TOKEN=github_pat_...' > .env"
    exit 1
fi

# Build and start the container in detached mode
docker compose -f .devcontainer/docker-compose.yml up -d --build
