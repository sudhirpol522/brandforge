FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 10001 brandforge \
    && useradd --system --uid 10001 --gid brandforge --create-home brandforge

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
RUN python -m pip install --upgrade pip \
    && python -m pip install ".[observability,temporal]"

RUN mkdir -p /app/data && chown -R brandforge:brandforge /app
USER brandforge

ENV PYTHONPATH=/app/src:/app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"

CMD ["opentelemetry-instrument", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
