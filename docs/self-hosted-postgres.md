# Self-Hosted Production Postgres (moving off Supabase)

## Why this is possible with zero app code changes

`apps/backend/app/config.py`'s `DATABASE_URL` is a plain SQLAlchemy/asyncpg
connection string — the backend never uses Supabase's client SDK or its
auto-generated REST API for data access, only standard Postgres. Local
dev already proves this: `docker-compose.yml` runs its own
`postgres:16-alpine` container, not Supabase, and the app doesn't know
the difference. Moving production off Supabase's Postgres is really just:
point `DATABASE_URL` at a different Postgres instance.

**What this does NOT cover**: Supabase Storage (`apps/backend/app/core/
storage.py`, used for design-image/voice-note uploads) is a separate,
Storage-API-specific piece — dropping Supabase entirely also means
replacing that (e.g. self-hosted MinIO), which isn't part of this guide.

## What you're setting up

A VPS running:

- `postgres:16-alpine`, with SSL forced on (both server- and client-side
  — see below), listening on port 5432.
- `postgres-backup-local`, taking daily/weekly/monthly gzipped `pg_dump`
  backups to `./backups` (a single VPS has none of Supabase's built-in
  redundancy, so this isn't optional).

The backend itself stays wherever it already runs (Render) — only the
database moves.

## Why SSL is mandatory here, not optional

`apps/backend/app/core/database.py` already hardcodes
`connect_args={"ssl": "require"}` for every non-SQLite connection —
that's what made the Supabase connection encrypted, and it applies
identically to whatever Postgres you point `DATABASE_URL` at. If this
server doesn't have SSL enabled, the backend simply can't connect — it's
not a config toggle you can skip.

`"require"` mode encrypts the connection but doesn't validate the
certificate authority, so a free self-signed certificate gives the same
real protection (nobody can read your traffic in transit) without
needing a domain name pointed at the VPS. If you do have a domain and
want full CA validation (`ssl="verify-full"`), swap in a Let's Encrypt
cert via certbot and update `database.py`'s `connect_args` — a
deliberate upgrade, not something scripted here.

## Setup steps

1. **Provision a VPS** with Docker + Docker Compose installed (any
   provider — Hetzner, DigitalOcean, your own hardware). Note its public
   IP.

2. **Copy these files onto it**: `docker-compose.prod.yml`,
   `postgres-prod-pg_hba.conf`, `scripts/generate-postgres-ssl-cert.sh`
   (either `git clone` the whole repo, or just these three).

3. **Generate the SSL cert** (once):

   ```bash
   ./scripts/generate-postgres-ssl-cert.sh
   ```

4. **Create a `.env`** next to `docker-compose.prod.yml`:

   ```
   POSTGRES_DB=vengaicode
   POSTGRES_USER=vengaicode_prod
   POSTGRES_PASSWORD=<generate a real random password, not a word you'd remember>
   ```

5. **Start it**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   docker compose -f docker-compose.prod.yml ps   # both services healthy?
   ```

## Firewall — be honest with yourself about what tier you're on

Ideally, only your backend's IP(s) can reach port 5432. The catch:
**Render's outbound IPs are dynamic on free/starter plans** — there's no
fixed IP to allowlist unless you're on a Render plan with the static
outbound IP add-on. Don't pretend otherwise. Two real options:

- **If you have (or add) a static outbound IP on Render**: allowlist it
  specifically, e.g. `ufw allow from <render-ip> to any port 5432 proto tcp`,
  then `ufw deny 5432` for everyone else.
- **If you don't**: the connection is exposed to the internet on port
  5432, so the rest of this setup carries the real weight —
  SSL-only via `pg_hba.conf` (already configured), a long random
  password (not the dev default), and consider `fail2ban` on the VPS
  to slow down brute-force scanning. This is a materially weaker
  posture than Supabase's network isolation — go in aware of that
  trade-off, it's the real cost of self-hosting on the cheaper tier.

## Migrating existing data from Supabase

Dump the whole database from Supabase (schema + data together — simpler
and avoids any drift from re-running `init_db()`'s `create_all()`
against an empty DB), then restore it into the new, empty instance:

```bash
# From your machine, using Supabase's connection string (Project Settings > Database):
pg_dump "postgresql://postgres:[password]@[supabase-host]:5432/postgres" \
  --no-owner --no-acl -Fc -f vengaicode_backup.dump

# Restore into the new self-hosted instance:
pg_restore --no-owner --no-acl \
  -h <vps-ip> -p 5432 -U vengaicode_prod -d vengaicode \
  vengaicode_backup.dump
```

## Pointing Render at the new database

In Render's dashboard, update the backend service's `DATABASE_URL`
environment variable to:

```
postgresql://vengaicode_prod:<password>@<vps-ip>:5432/vengaicode
```

(Same `postgresql://` scheme already used for Supabase —
`config.py`'s `database_url_async` property converts it to
`postgresql+asyncpg://` automatically.) Redeploy, then check `/health`
and watch the logs for a successful DB connection.

## Restoring from a backup

```bash
gunzip -c backups/daily/vengaicode-YYYYMMDD.sql.gz | \
  psql -h <vps-ip> -U vengaicode_prod -d vengaicode
```

## What you're now responsible for (that Supabase used to handle)

OS/Docker security patching on the VPS, disk space for `./backups`
growing over time, and noticing if the instance goes down (see the
uptime-monitoring recommendation from earlier — this is exactly the
kind of thing it's for). None of this is automated by this setup;
it's the real, ongoing cost of the money you're saving.
