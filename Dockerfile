# Dockerfile
FROM ghcr.io/astral-sh/uv:alpine3.21


# Install git (to read commit metadata) and CA certs (for HTTPS to Slack)
RUN apk add --no-cache git ca-certificates && update-ca-certificates

#App setup
WORKDIR /app
# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Ensure installed tools can be executed out of the box
ENV UV_TOOL_BIN_DIR=/usr/local/bin

# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

# Run as non-root
RUN adduser -D appuser && chown -R appuser /app
USER appuser

# Helpful defaults

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


# Execute the notifier
ENTRYPOINT ["uv","run", "/app/notify_on_failure.py"]

