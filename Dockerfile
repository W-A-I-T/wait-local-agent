FROM node:22-slim AS ui-build

WORKDIR /ui

COPY ui/package*.json ./
RUN npm ci --no-audit --no-fund

COPY ui/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WAIT_DATA_PATH=/data/state.db \
    WAIT_ALLOWED_DOC_ROOT=/app/examples/sample_docs \
    WAIT_DEMO_MODE=false \
    WAIT_SECRETS_BACKEND=env \
    WAIT_VAULT_PATH=/data/vault \
    WAIT_UI_DIST=/app/ui-dist

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir . \
    && groupadd --system --gid 10001 wait \
    && useradd --system --uid 10001 --gid wait --home-dir /app --no-create-home wait \
    && mkdir -p /data \
    && chown -R wait:wait /app /data

COPY --from=ui-build /ui/dist ./ui-dist

USER wait

EXPOSE 8788

HEALTHCHECK --interval=10s --timeout=5s --retries=5 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8788/healthz', timeout=3)"]

CMD ["wait-local-agent", "serve", "--host", "0.0.0.0", "--port", "8788"]
