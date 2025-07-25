#!/usr/bin/env bash

# shellcheck disable=SC1091

set -e

# Load environment variables from .env file if it exists
if [[ -f .env ]]; then
    source .env
fi

MODEL="${MODEL:-granite3.2:8b-instruct-q8_0}"
LLM_PROVIDER="${LLM_PROVIDER:-ollama}"
LLM_MODEL="${LLM_MODEL:-$MODEL}"
OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://localhost:11434}"

OLLAMA_PID=""

# Export environment variables for mcp-cli
export LLM_PROVIDER
export LLM_MODEL
export OLLAMA_API_BASE

# Cleanup function
cleanup() {
    echo ""
    echo "Shutting down..."

    # Kill ollama if we started it
    if [[ -n "$OLLAMA_PID" ]]; then
        echo "Stopping ollama server..."
        kill "$OLLAMA_PID" 2>/dev/null || true
        wait "$OLLAMA_PID" 2>/dev/null || true
    fi

    echo "Cleanup complete"
    exit 0
}

# Setup signal handlers
trap cleanup SIGINT SIGTERM EXIT

# Start ollama server if not running
start_ollama() {
    if ! pgrep -x "ollama" > /dev/null; then
        echo "Starting ollama server..."
        ollama serve > /dev/null 2>&1 &
        OLLAMA_PID=$!
        sleep 2
    else
        echo "Ollama server already running"
    fi
}

# Ensure model is available
ensure_model() {
    if ! ollama list | grep -q "$LLM_MODEL"; then
        echo "Pulling $LLM_MODEL model..."
        ollama pull "$LLM_MODEL"
    else
        echo "$LLM_MODEL model already available"
    fi
}

# Run mcp-cli
run_mcp() {
    echo "Starting mcp-cli with libvirt-mcp server..."
    echo "Using provider: $LLM_PROVIDER, model: $LLM_MODEL"
    echo "Press Ctrl+C to exit"
    echo ""
    # Use interactive mode with environment variables for provider and model
    # Run in foreground to maintain proper terminal I/O
    uvx mcp-cli --config-file server_config.json interactive
}

main() {
    echo "Starting libvirt-mcp demo with $LLM_PROVIDER and $LLM_MODEL model..."
    start_ollama
    ensure_model
    run_mcp
}

main
