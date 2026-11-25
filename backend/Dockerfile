# API image. Build context: backend/. Runs as app_user via APP_DATABASE_URL;
# the same image runs migrations (owner URL) in the compose `migrate` service.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.13.10 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
# Fallback: in some Codespaces uv's TLS handshake to PyPI stalls while pip's
# works (docs/PROGRESS.md). pip installs the same locked, hash-pinned set.
RUN UV_HTTP_TIMEOUT=20 uv sync --frozen --no-dev --no-install-project \
 || ( echo "uv sync failed; installing the locked set with pip" \
      && uv export --frozen --no-dev --no-emit-project -q > /tmp/requirements.txt \
      && uv venv --allow-existing -q /opt/venv \
      && /opt/venv/bin/python -m ensurepip > /dev/null \
      && /opt/venv/bin/python -m pip install -q --no-cache-dir \
           --require-hashes --no-deps -r /tmp/requirements.txt \
      && rm /tmp/requirements.txt \
      && uv sync --frozen --no-dev --no-install-project --offline )

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN useradd --system --uid 10001 --no-create-home app \
 && mkdir -p /data/uploads /data/hf-cache \
 && chown -R app /data
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
