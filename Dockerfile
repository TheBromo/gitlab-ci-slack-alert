# Dockerfile
FROM python:3.12-alpine

# Install git (to read commit metadata) and CA certs (for HTTPS to Slack)
RUN apk add --no-cache git ca-certificates && update-ca-certificates

#App setup
WORKDIR /app
COPY notify_on_failure.py /app/notify_on_failure.py

# Run as non-root
RUN adduser -D appuser && chown -R appuser /app
USER appuser

# Helpful defaults
ENV PYTHONUNBUFFERED=1

# Execute the notifier
ENTRYPOINT ["python", "/app/notify_on_failure.py"]

