FROM python:3.12-slim-bookworm

ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN python -m pip install --index-url "$PIP_INDEX_URL" \
    --retries 10 --timeout 120 -r backend/requirements.txt

# API 容器只复制后端代码，不携带 Streamlit 页面和本地密钥文件。
COPY backend ./backend
COPY quant_core ./quant_core

RUN groupadd --system api \
    && useradd --system --gid api --create-home api \
    && chown -R api:api /app

USER api

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"]

CMD ["python", "-m", "backend.start_api"]
