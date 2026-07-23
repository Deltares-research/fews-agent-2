#!/bin/sh
# Run the API + Streamlit + nginx in one container, one exposed port (8501).
# Both shells share the same projects/ store on this disk, so a session
# created over HTTP is instantly visible in the UI and vice versa.
set -e

# SSH for `az webapp ssh` / `az webapp create-remote-connection` — bound
# to 2222, reachable only via the Azure management plane (RBAC-gated).
# HARD GATE: start sshd ONLY on App Service (Azure injects
# WEBSITE_INSTANCE_ID there). Anywhere else — local docker, a VM, any
# host that might publish 2222 — this image must never run an ssh
# daemon with the documented root password.
if [ -n "$WEBSITE_INSTANCE_ID" ] && [ -x /usr/sbin/sshd ]; then
    /usr/sbin/sshd
fi

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
