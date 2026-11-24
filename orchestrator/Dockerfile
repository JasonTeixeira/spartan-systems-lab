FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/spartan-orchestrator

RUN adduser --disabled-password --gecos "" orchestrator

COPY pyproject.toml uv.lock ./
COPY orchestrator ./orchestrator
COPY tools ./tools

RUN pip install --no-cache-dir fastapi uvicorn[standard] pydantic

USER orchestrator

EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz')"

CMD ["uvicorn", "orchestrator.app:app", "--host", "0.0.0.0", "--port", "8090"]
