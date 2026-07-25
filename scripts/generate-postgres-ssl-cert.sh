#!/usr/bin/env bash
# Generates a self-signed TLS cert/key for the self-hosted production
# Postgres (docker-compose.prod.yml). Run this ONCE on the VPS, before
# `docker compose -f docker-compose.prod.yml up -d`.
#
# Self-signed (not Let's Encrypt) is deliberate here: apps/backend/app/
# core/database.py connects with ssl="require" mode, which encrypts the
# connection but does NOT validate the certificate authority — so a
# self-signed cert gives the same real protection (traffic can't be
# read in transit) without needing a domain name pointed at this VPS.
# If you DO have a domain for this box and want full CA validation
# (ssl="verify-full"), use certbot/Let's Encrypt instead and update
# database.py's connect_args accordingly — that's a deliberate upgrade,
# not something this script does for you.
set -euo pipefail

OUT_DIR="$(dirname "$0")/../postgres-ssl"
mkdir -p "$OUT_DIR"

if [[ -f "$OUT_DIR/server.key" ]]; then
  echo "postgres-ssl/server.key already exists — refusing to overwrite." >&2
  echo "Delete it first if you really want to regenerate (this will invalidate the old cert)." >&2
  exit 1
fi

openssl req -new -x509 -days 3650 -nodes \
  -out "$OUT_DIR/server.crt" \
  -keyout "$OUT_DIR/server.key" \
  -subj "/CN=vengaicode-postgres"

# Postgres refuses to start if the key is group/world-readable, and the
# container runs as the postgres user (uid 70 in postgres:16-alpine).
chmod 600 "$OUT_DIR/server.key"
chown 70:70 "$OUT_DIR/server.key" "$OUT_DIR/server.crt" 2>/dev/null || \
  echo "Note: couldn't chown to uid 70 (not running as root?) — do this manually before starting the container."

echo "Generated postgres-ssl/server.crt + server.key (valid 10 years)."
