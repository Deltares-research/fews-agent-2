# Dockerfile — FEWS configurator agent (chat UI)
#
# Builds a runnable Streamlit container that wraps the chat agent.
# Two stages so the runtime image doesn't carry the compiler toolchain
# needed for the lxml wheel build on linux/arm64.
#
# Expected runtime: Ollama running on the host (e.g. `ollama serve`).
# The container reaches it through OLLAMA_HOST — defaults to
# host.docker.internal:11434, which Docker Desktop (Mac/Windows)
# resolves out of the box. On Linux pass:
#     --add-host=host.docker.internal:host-gateway
# at `docker run`, or override OLLAMA_HOST to point at the actual
# endpoint (e.g. another container in a compose network).
#
# Build:
#     docker build -t fews-agent .
#
# Run (Mac/Windows):
#     docker run --rm -p 8501:8501 \
#         -v "$(pwd)/sessions":/app/sessions \
#         -v "$(pwd)/projects":/app/projects \
#         fews-agent
#
# Run (Linux):
#     docker run --rm -p 8501:8501 \
#         --add-host=host.docker.internal:host-gateway \
#         -v "$(pwd)/sessions":/app/sessions \
#         -v "$(pwd)/projects":/app/projects \
#         fews-agent

# ---------------------------------------------------------------------
# Stage 1: build deps + venv
# ---------------------------------------------------------------------
FROM python:3.11-slim AS builder

# build-essential + libxml2/libxslt headers for lxml when no wheel
# matches the runner's arch (notably linux/arm64 on Apple Silicon).
# Corporate networks intermittently kill plain-HTTP downloads from the
# Debian CDN (observed: Fastly 151.101.x.x:80 timeouts mid-fetch) — use
# HTTPS + retries for apt.
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libxml2-dev \
        libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies into a clean venv so we can copy just that into
# the runtime stage. Source code is copied too because pyproject uses
# poetry-core, which needs the package source to resolve [project].
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip

WORKDIR /build
COPY pyproject.toml README.md ./
COPY fews_agent/ ./fews_agent/

# `pip install .` pulls every dep declared under [project.dependencies]
# in pyproject.toml. pyyaml is used by project_chat.py / chatter.py
# but isn't listed in pyproject (known gap noted in CLAUDE.md) —
# install it explicitly here so the runtime works out of the box.
RUN pip install --no-cache-dir . pyyaml

# ---------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------
FROM python:3.11-slim

# Runtime shared libs for lxml + nginx (single-port front for API+UI).
# No compilers in the final image. Same HTTPS+retries apt fix as the
# builder stage (corporate networks kill plain-HTTP CDN fetches).
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources \
    && printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
        git \
        nginx \
        openssh-server \
    && rm -rf /var/lib/apt/lists/* \
    && echo "root:Docker!" | chpasswd \
    && mkdir -p /run/sshd

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Application source — keep these COPYs explicit so the .dockerignore
# stays the source of truth for what's excluded.
COPY app/        ./app/
COPY frontend/   ./frontend/
COPY fews_agent/ ./fews_agent/
COPY runners/    ./runners/
COPY docker/     ./docker/
COPY docker-entrypoint-web.sh ./
RUN chmod +x docker-entrypoint-web.sh
COPY CLAUDE.md   ./

# These live outside the image — bind-mount at run time so chat
# sessions and built projects survive container restarts.
RUN mkdir -p sessions projects

# Streamlit config: headless (no browser autolaunch), listen on all
# interfaces, suppress the usage-stats prompt that blocks first boot.
ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# LLM backend selection — see fews_agent/agent/providers/factory.py.
# Default = ollama on the host. To run against Azure OpenAI instead
# (cloud deployment), set these at `docker run` / App Settings time:
#
#     FEWS_AGENT_PROVIDER=AZURE
#     AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
#     AZURE_OPENAI_API_KEY=<resource-key>
#     FEWS_AGENT_MODEL=<deployment-name>
#
# Real process env wins over .env, so the image needs no rebuild to
# switch providers — set them in Azure Container Apps / App Service
# configuration and restart.
ENV FEWS_AGENT_PROVIDER=ollama

# Default points at the host's Ollama (used only when provider=ollama).
# Override at `docker run` time with `-e OLLAMA_HOST=http://...` for
# compose / remote setups.
ENV OLLAMA_HOST=http://host.docker.internal:11434

COPY docker/sshd_config /etc/ssh/sshd_config

EXPOSE 8501 2222

# One container, three processes, ONE exposed port: nginx on 8501 routes
# /api/* to FastAPI (uvicorn) and everything else to Streamlit. Both shells
# share the same projects/ store, so HTTP-created sessions appear in the UI.
CMD ["./docker-entrypoint-web.sh"]
