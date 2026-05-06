FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WAIT_DATA_PATH=/data/state.db \
    WAIT_ALLOWED_DOC_ROOT=/app/examples/sample_docs

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples

RUN python -m pip install --upgrade pip \
    && python -m pip install .

EXPOSE 8788

CMD ["wait-local-agent", "serve", "--host", "0.0.0.0", "--port", "8788"]
