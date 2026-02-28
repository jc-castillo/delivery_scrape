# =============================================================================
# Delivery Scrape Development Container
# Miniforge (conda) base + Python + GitHub CLI + Claude Code
# =============================================================================

FROM condaforge/miniforge3@sha256:40c11cadd6fe3a0e4f60bd10438db470e1934dcc34e703add9796cf1cd7f7169

ARG DEBIAN_FRONTEND=noninteractive

# ── System packages ──────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    wget \
    ssh \
    sudo \
    build-essential \
    ca-certificates \
    gnupg \
    pkg-config \
    zsh \
    && rm -rf /var/lib/apt/lists/*

# ── GitHub CLI ──────────────────────────────────────────────────────────────
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# ── Node.js 20 LTS (for Claude Code) ────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# ── Claude Code CLI ─────────────────────────────────────────────────────────
RUN npm install -g @anthropic-ai/claude-code

# ── Conda environment (Python packages) ──────────────────────────────────────
COPY .devcontainer/environment.yml /tmp/environment.yml
RUN conda env update -n base -f /tmp/environment.yml \
    && conda clean -afy

# ── Non-root user ────────────────────────────────────────────────────────────
RUN useradd -m -s /bin/zsh dev \
    && echo "dev ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER dev

# ── Git config (use GH_TOKEN for HTTPS auth instead of SSH) ─────────────────
RUN git config --global credential.helper '!f() { echo "password=${GH_TOKEN}"; }; f' \
    && git config --global url."https://github.com/".insteadOf "git@github.com:" \
    && git config --global user.email "noreply@container" \
    && git config --global user.name "Claude (container)"

# ── Default working directory ────────────────────────────────────────────────
WORKDIR /home/dev/delivery_scrape

CMD ["zsh"]
