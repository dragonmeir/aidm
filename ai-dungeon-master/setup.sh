#!/bin/bash
# AI Dungeon Master - Setup Script
# Run this once to set everything up on a fresh Linux box.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  AI Dungeon Master - Setup"
echo "  OSE/OSR Edition v0.2.0"
echo "========================================"
echo

# ── Check prerequisites ─────────────────────────────────────

echo "[1/6] Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python: $PYTHON_VERSION"

if ! command -v ollama &>/dev/null; then
    echo "  Ollama not found. Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "  Ollama: $(ollama --version 2>/dev/null || echo 'installed')"
fi

# ── Create virtual environment ──────────────────────────────

echo
echo "[2/6] Setting up Python virtual environment..."

if [ ! -f ".venv/bin/activate" ]; then
    echo "  Creating virtual environment..."
    rm -rf .venv
    python3 -m venv --clear .venv
    echo "  Created .venv"
else
    echo "  .venv already exists"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

# Ensure pip is available
if ! command -v pip &>/dev/null; then
    echo "  Installing pip into venv..."
    python3 -m ensurepip --upgrade
fi

# ── Install dependencies ────────────────────────────────────

echo
echo "[3/6] Installing Python dependencies..."
pip install --upgrade pip -q
pip install -e . -q
echo "  Dependencies installed"

# ── Pull Ollama models ──────────────────────────────────────

echo
echo "[4/6] Pulling Ollama models..."

# Make sure Ollama is running
if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
    echo "  Starting Ollama service..."
    sudo systemctl start ollama 2>/dev/null || ollama serve &>/dev/null &
    sleep 3
fi

# Read model from config
MODEL=$(python3 -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c.get('ollama',{}).get('model','dolphin-mixtral:8x7b'))")
echo "  Pulling DM model: $MODEL"
ollama pull "$MODEL"

# ── Create data directories ─────────────────────────────────

echo
echo "[5/6] Setting up data directories..."
mkdir -p data/sessions data/chroma_db data/maps
echo "  Data directories ready"

# ── Install systemd service ─────────────────────────────────

echo
echo "[6/6] Installing systemd service..."

# Update service file with actual paths
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$SCRIPT_DIR|" aidm.service
sed -i "s|Environment=PATH=.*|Environment=PATH=$SCRIPT_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin|" aidm.service
sed -i "s|ExecStart=.*|ExecStart=$SCRIPT_DIR/.venv/bin/python -m uvicorn src.server:app --host 0.0.0.0 --port 8000|" aidm.service
sed -i "s|User=.*|User=$(whoami)|" aidm.service
sed -i "s|Group=.*|Group=$(whoami)|" aidm.service

if sudo -n true 2>/dev/null; then
    sudo cp aidm.service /etc/systemd/system/aidm.service
    sudo systemctl daemon-reload
    sudo systemctl enable aidm.service
    echo "  Service installed and enabled"
else
    echo "  Skipping systemd install (needs sudo)."
    echo "  To install manually:"
    echo "    sudo cp $SCRIPT_DIR/aidm.service /etc/systemd/system/"
    echo "    sudo systemctl daemon-reload && sudo systemctl enable aidm"
fi

echo
echo "========================================"
echo "  Setup complete!"
echo "========================================"
echo
echo "  To ingest PDFs:     source .venv/bin/activate && aidm ingest"
echo "  To start server:    sudo systemctl start aidm"
echo "  To start manually:  source .venv/bin/activate && aidm serve"
echo "  Web frontend:       http://localhost:8000/play"
echo "  API docs:           http://localhost:8000/docs"
echo "  CLI mode:           source .venv/bin/activate && aidm play"
echo
echo "  Server logs:        journalctl -u aidm -f"
echo
