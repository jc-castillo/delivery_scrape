#!/usr/bin/env bash
# =============================================================================
# Set up the Python environment on an HPC cluster (no root required)
#
# Usage:
#   bash .devcontainer/setup-cluster.sh
#
# Prerequisites:
#   - Internet access (for downloading miniforge and packages)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Miniforge (conda in userspace) ─────────────────────────────────────────
CONDA_DIR="$HOME/miniforge3"

if [ ! -d "$CONDA_DIR" ]; then
    echo "Installing miniforge..."
    ARCH=$(uname -m)  # x86_64 or aarch64
    curl -fsSL "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-${ARCH}.sh" \
        -o /tmp/miniforge.sh
    bash /tmp/miniforge.sh -b -p "$CONDA_DIR"
    rm /tmp/miniforge.sh
    echo "Miniforge installed to $CONDA_DIR"
else
    echo "Miniforge already installed at $CONDA_DIR"
fi

# Make conda available in this script
eval "$("$CONDA_DIR/bin/conda" shell.bash hook)"

# ── Conda environment (Python packages) ─────────────────────────────────────
ENV_NAME="delivery-scrape"

if conda env list | grep -q "$ENV_NAME"; then
    echo "Updating existing conda environment '$ENV_NAME'..."
    conda env update -n "$ENV_NAME" -f "$SCRIPT_DIR/environment.yml"
else
    echo "Creating conda environment '$ENV_NAME'..."
    conda env create -n "$ENV_NAME" -f "$SCRIPT_DIR/environment.yml"
fi

conda activate "$ENV_NAME"

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo "Setup complete. To use:"
echo "  conda activate $ENV_NAME"
echo ""
echo "Add to your .bashrc for convenience:"
echo "  eval \"\$(~/miniforge3/bin/conda shell.bash hook)\""
echo "  conda activate $ENV_NAME"
