# Hugging Face Spaces Dockerfile for Self-Healing DevOps Sandbox
FROM ghcr.io/meta-pytorch/openenv-base:latest AS builder

USER root

# Install Node.js 20 & utilities needed by the sandbox
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl bash && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /server_app

# Copy environment code
COPY . /server_app/env
WORKDIR /server_app/env

# Ensure uv is available
RUN if ! command -v uv >/dev/null 2>&1; then \
        curl -LsSf https://astral.sh/uv/install.sh | sh && \
        mv /root/.local/bin/uv /usr/local/bin/uv && \
        mv /root/.local/bin/uvx /usr/local/bin/uvx; \
    fi

# Install dependencies using uv sync
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then \
        uv sync --no-install-project --no-editable; \
    else \
        uv sync --no-editable; \
    fi

# Final runtime stage
FROM ghcr.io/meta-pytorch/openenv-base:latest

USER root

# Re-install Node.js 20 in the runtime image
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl bash psmisc && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /server_app

# Copy the virtual environment from builder
COPY --from=builder /server_app/env/.venv /server_app/.venv

# Copy the environment code
COPY --from=builder /server_app/env /server_app/env

# Ensure the backup folder for reset() is available and perfectly clean
# The environment script will do `cp -r /app_backup/* /app/` during every reset
RUN mkdir -p /app_backup && \
    cp -r /server_app/env/simulated_app/* /app_backup/ && \
    mkdir -p /app && \
    chmod -R 777 /app /app_backup

# Export Paths
ENV PATH="/server_app/.venv/bin:$PATH"
ENV PYTHONPATH="/server_app/env:$PYTHONPATH"

# Run the FastAPI server on port 7860 for HuggingFace Spaces
ENV ENABLE_WEB_INTERFACE=true
EXPOSE 7860

CMD ["sh", "-c", "cd /server_app/env && uvicorn server.app:app --host 0.0.0.0 --port 7860"]
