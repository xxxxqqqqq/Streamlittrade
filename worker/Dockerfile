FROM python:3.12-slim-bookworm

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt backend/requirements-worker.txt ./backend/
RUN python -m pip install --index-url "$PIP_INDEX_URL" \
    --retries 10 --timeout 120 -r backend/requirements-worker.txt

# Worker拥有量化核心；API容器不执行CPU密集回测。
COPY backend ./backend
COPY quant_core ./quant_core
COPY strategies.py ./strategies.py
COPY scripts/benchmark_feature_materialization.py ./scripts/benchmark_feature_materialization.py

RUN groupadd --gid 10001 worker \
    && useradd --uid 10001 --gid worker --create-home worker \
    && mkdir -p /var/lib/quantforge-worker \
    && chown -R worker:worker /app /var/lib/quantforge-worker

USER worker

CMD ["python", "-m", "backend.app.workers.main"]
