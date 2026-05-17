FROM node:22-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv

WORKDIR /app

# Layer caching: install Python deps before copying full source
COPY pyproject.toml setup.cfg setup.py ./
COPY backend/__init__.py backend/__init__.py
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --no-deps -e .

# Layer caching: install Node deps before copying full frontend source
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd /app/frontend && npm ci

# Copy full source and finalise installs
COPY . .
RUN pip install --no-cache-dir -e . \
    && chmod +x /app/scripts/start-web.sh \
    && cd /app/frontend && npm run build

# Non-root user for production
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser \
    && chown -R appuser:appuser /app /opt/venv
USER appuser

EXPOSE 5177 8877

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python3 -c "import urllib.request; r=urllib.request.urlopen('http://localhost:8877/api/v1/health'); assert r.status==200" || exit 1

CMD ["/app/scripts/start-web.sh"]
