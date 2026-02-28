# Development Container

This folder defines a Docker container for running Claude Code with full
permissions in an isolated environment. You keep editing files in Cursor on
your Mac — the container is only for **execution**.

## What's in here

| File                 | Purpose                                                    |
|----------------------|------------------------------------------------------------|
| `Dockerfile`         | Builds an image with Python, GitHub CLI, and Claude Code   |
| `docker-compose.yml` | Mounts your project and Claude auth into the container     |
| `build.sh`           | Checks for GH_TOKEN and builds/starts the container        |
| `start.sh`           | Builds if needed, then drops you into a shell              |
| `claude.sh`          | Builds if needed, then runs Claude Code directly           |

## How it works

- Your project is mounted at `/home/dev/delivery_scrape` inside the container,
  so edits in Cursor appear instantly and outputs (CSVs, Parquet) appear on your Mac.
- Your `~/.claude` directory is mounted so Claude Code inherits your existing
  login — no API key needed.
- A `GH_TOKEN` in `.env` is used for git authentication inside the container.

## Usage

1. Make sure Docker Desktop is running.
2. From the project root:
   ```bash
   # Interactive shell
   .devcontainer/start.sh

   # Or run Claude Code directly
   .devcontainer/claude.sh
   ```

## What gets committed to git

Only the files in this folder (configuration). The Docker image itself —
including all downloaded Python packages — lives locally on your machine and
is never pushed to GitHub.
