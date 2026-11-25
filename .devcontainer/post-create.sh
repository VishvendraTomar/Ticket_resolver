#!/usr/bin/env bash
# One-time setup for a new Codespace / devcontainer. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Local .env with random passwords (never committed; see .env.example).
if [[ ! -f .env ]]; then
  rand() { head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
  owner_pw=$(rand 32)
  app_pw=$(rand 40)
  sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${owner_pw}|" \
      -e "s|^APP_DB_PASSWORD=.*|APP_DB_PASSWORD=${app_pw}|" \
      -e "s|^AUTH_PROVIDER=.*|AUTH_PROVIDER=fake|" \
      .env.example > .env
  chmod 600 .env
  echo "post-create: wrote .env (local passwords, AUTH_PROVIDER=fake)"
fi

# 2. Python 3.12 (uv-managed, pinned by backend/.python-version) and locked deps.
cd backend
uv python install
synced=false
for attempt in 1 2 3; do
  if uv sync --frozen; then synced=true; break; fi
  echo "post-create: uv sync attempt ${attempt} failed; retrying"
done
if [[ "$synced" != true ]]; then
  # Seen in Codespaces: uv's TLS handshake to PyPI stalls while OpenSSL clients
  # work. Install the same locked, hash-pinned set with pip, then let uv verify.
  echo "post-create: falling back to pip for the locked dependency set"
  reqs=$(mktemp)
  uv export --frozen --no-emit-project -q > "$reqs"
  uv venv --allow-existing -q
  .venv/bin/python -m ensurepip > /dev/null
  .venv/bin/python -m pip install -q --require-hashes --no-deps -r "$reqs"
  rm -f "$reqs"
  uv sync --frozen --offline
fi
cd ..

# 3. Web app dependencies (locked).
(cd web && npm ci --no-audit --no-fund)

# 4. Git hooks (pre-commit). Falls back to pip for the same uv TLS issue.
if ! command -v pre-commit >/dev/null; then
  uv tool install pre-commit \
    || { python3 -m venv "$HOME/.local/pre-commit-venv" \
         && "$HOME/.local/pre-commit-venv/bin/pip" install -q pre-commit \
         && mkdir -p "$HOME/.local/bin" \
         && ln -sf "$HOME/.local/pre-commit-venv/bin/pre-commit" "$HOME/.local/bin/pre-commit"; }
fi
"$HOME/.local/bin/pre-commit" install || pre-commit install

# 5. Database: start Compose and migrate (creates app_user with NOBYPASSRLS).
docker compose up -d --wait
(cd backend && uv run --frozen alembic upgrade head)

echo "post-create: done. Run: cd backend && uv run pytest"
