FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY odos ./odos
COPY eval ./eval
COPY config.yaml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[all]"

RUN useradd --create-home odos
USER odos

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["uvicorn", "odos.backend.api:app", "--host", "0.0.0.0", "--port", "8000"]
