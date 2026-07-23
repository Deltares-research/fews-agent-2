#!/bin/sh
# Run the API + Streamlit + nginx in one container, one exposed port (8501).
# Both shells share the same projects/ store on this disk, so a session
# created over HTTP is instantly visible in the UI and vice versa.
set -e

# FastAPI — internal only; nginx serves it at /api/ (prefix stripped, so
# root_path tells FastAPI how to write its /docs URLs).
uvicorn app.api.server:app --host 127.0.0.1 --port 8000 \
    --root-path /api &

# Streamlit — internal only; nginx fronts it.
streamlit run frontend/web_app.py \
    --server.port 8601 --server.address 127.0.0.1 \
    --server.headless true &

# nginx in the foreground owns the container lifecycle.
exec nginx -c /app/docker/nginx.conf -g "daemon off;"
