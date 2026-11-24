FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/spartan-orchestrator

# Real Linux SRE forensics & systems engineering toolchain for interactive PTY War-Rooms
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    dnsutils \
    file \
    git \
    iproute2 \
    jq \
    less \
    lsof \
    nano \
    openssl \
    procps \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos "" orchestrator

COPY pyproject.toml uv.lock ./
COPY orchestrator ./orchestrator
COPY tools ./tools

RUN pip install --no-cache-dir fastapi uvicorn[standard] pydantic

RUN mkdir -p /tmp/spartan-sandboxes && chown -R orchestrator:orchestrator /tmp/spartan-sandboxes /srv/spartan-orchestrator

USER orchestrator

EXPOSE 8090

HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz')"

CMD ["uvicorn", "orchestrator.app:app", "--host", "0.0.0.0", "--port", "8090"]
