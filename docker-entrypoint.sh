#!/usr/bin/env bash
# Entrypoint for Dockerfile.bundled: bring up the bundled Ollama server,
# ensure the model is present, then hand off to the container command
# (Streamlit by default; `bash` for an interactive terminal).
set -euo pipefail

MODEL="${FEWS_AGENT_MODEL:-qwen2.5:7b-instruct}"

# Start Ollama in the background. It binds the address in OLLAMA_HOST.
ollama serve &

# Wait until the server answers (a few seconds on a warm box).
echo "waiting for ollama to come up..."
for _ in $(seq 1 60); do
    if ollama list >/dev/null 2>&1; then
        echo "ollama is up"
        break
    fi
    sleep 1
done

# Ensure the model is available. No-op if it's already in the mounted volume,
# so this only downloads on the very first run. '|| true' so a transient pull
# failure doesn't kill the container — the agent surfaces model errors itself.
echo "ensuring model: ${MODEL}"
ollama pull "${MODEL}" || true

# Hand off to the container command (PID-1 via exec). Default: streamlit.
exec "$@"
