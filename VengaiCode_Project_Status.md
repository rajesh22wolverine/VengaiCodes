# VengaiCode — Project Status

**Last updated:** 2026-09-04 (after `d83ee8ff` — task-aware AI model routing + per-user token quota)
**Working tree:** clean except this file. Untracked: `apps/backend/local_dev.db.backup-presession` (should be gitignored).

---

## 1. Live Infrastructure

| Piece | Service / Location | Notes |
|---|---|---|
| **Code** | GitHub `rajesh22wolverine/VengaiCodes` (**public**), branch `main` | pnpm + Turborepo monorepo. Auto-deploys backend to Render on push. Confirmed public via the GitHub API on 2026-09-04 (this doc previously said private) — which also means **unlimited free GitHub Actions minutes** on standard runners. |
| **Backend** | Render free tier → `https://vengaicode-backend.onrender.com` | FastAPI, Python 3.11, ~108 routes. Last confirmed 200 on `/health`: 2026-07-31. |
| **Database** | **Supabase Postgres** (session pooler, SSL required) | Plain `DATABASE_URL` + SQLAlchemy/asyncpg — no Supabase SDK or PostgREST anywhere, so the DB is portable. |
| **Object storage** | **Supabase Storage**, bucket `design-uploads` (must be public) | `app/core/storage.py`, raw httpx REST. Used for design-image-to-code uploads. |
| **Cache / rate limit / JWT blocklist** | **Upstash Redis** | `app/core/redis.py`. Fail-open by design — everything degrades gracefully when Redis is unreachable. |
| **AI (platform default)** | **Groq** | In-code default in `config.py` = `openai/gpt-oss-120b` (fixed 2026-09-04). Groq retired `llama-3.3-70b-versatile` on **2026-08-16** for free/developer keys, which 404'd every generation phase into a 503. `retire_decommissioned_groq_models()` runs at startup and repoints platform bag rows off dead model ids. The live bag reads `model_name` off the DB row, so a redeploy fixes generation on its own. Confirmed working in production the same day (`200 OK` from `openai/gpt-oss-120b` in the Render logs). Render's `GROQ_DEFAULT_MODEL` env var is **still pinned to the retired model**, but can no longer do harm: `Settings.substitute_retired_groq_models()` rejects a decommissioned id from any source (env included) and logs a warning. Set `GROQ_ALLOW_RETIRED_MODELS=true` to opt out, e.g. on an enterprise contract that still serves it. Tidying the Render env var is now optional housekeeping, not a fix. |
| **SMS / OTP** | **MSG91** | `app/services/msg91_service.py` |
| **CI / user-app builds** | **GitHub Actions** — 18 workflows | Triggered by the backend via `repository_dispatch` using `GITHUB_TOKEN` / `GITHUB_REPO` / `BUILD_SECRET`. |
| **Mobile builds** | **Expo EAS** — org `vengaicode`, project `vengaicode-mobile` | projectId `dd862d0d-90d4-4c15-adfa-3ead014a09b2` |
| **Dev machine** | Local Windows 11 | Docker/Ollama still will not run here (RAM). Oracle Cloud free tier still blocked on debit-card verification. |

**⚠️ Open infra item:** `gh` CLI is **not logged in** on this machine (the dead `KalRaj2` entry was removed 2026-09-04). Run `gh auth login -h github.com -w` once — until then, CI runs can only be inspected via the unauthenticated public GitHub API, and workflows cannot be dispatched manually.

**⚠️ Action on Render:** `GITHUB_REPO` **must be** `rajesh22wolverine/VengaiCodes` — format is `owner/repo`, no `https://`, no `.git`. It is interpolated straight into `https://api.github.com/repos/{GITHUB_REPO}/dispatches`. If an older deployment still holds `KalRaj2/VengaiCodes`, every packaging build is dispatching at a dead repo. Now documented in `env.example`, but **env.example does not configure Render** — set it in the Render dashboard (Service → Environment) and redeploy.

---

## 2. App Inventory

| Path | What it is | State |
|---|---|---|
| `apps/backend` | FastAPI backend, 88 `.py` files | ✅ Real, deployed |
| `apps/desktop` | VengaiCode's **own** client — Tauri v1.5 + React 18 + Vite + TS, Redux Toolkit, Monaco, GrapesJS | ✅ Real. Live `.msi` + `.exe` built locally 2026-07-26 and again 2026-07-31 |
| `apps/mobile` | VengaiCode's **own** client — Expo / React Native + expo-router | ✅ Real. Live APK built via EAS 2026-07-26 and 2026-07-31 |
| `apps/admin` | — | ❌ **Empty folder skeleton, 0 files.** The real admin UI lives inside desktop + mobile |
| `apps/marketplace` | — | ❌ **Empty folder skeleton, 0 files.** Backend `marketplace.py` + desktop marketplace screens do exist |
| `templates/` | `tauri-windows`, `tauri-linux`, `capacitor-android`, `console`, `game`, `o3de` | ✅ Used by the packaging pipelines |
| `.gitea/` | — | ❌ Empty |

> Do not conflate **VengaiCode's own apps** (`apps/desktop`, `apps/mobile`) with the **per-project generation pipelines** that package end users' generated apps. Different code, different workflows.

---

## 3. SDLC Phase Status

The old Sprint 1–7 numbering is retired — everything through Export is built. Current state:

| Phase | Status | How it was verified |
|---|---|---|
| Auth (signup / OTP / login / forgot-password) | ✅ Live | End-to-end, repeatedly |
| Dashboard + Projects CRUD | ✅ Live | End-to-end |
| 7-layer AI Wizard | ✅ Live | End-to-end |
| Requirements (FRD JSON) | ✅ Live | End-to-end |
| UI/UX Design generation | ✅ Live | End-to-end |
| ↳ Page preview / click-to-edit / reorder | ✅ Live | Playwright |
| ↳ **Design Studio** (GrapesJS drag-and-drop canvas) | ✅ Desktop live-verified (Playwright) · 🟡 Mobile WebView typecheck-only | Found and fixed a real CSP / Font-Awesome bug during verification |
| ↳ **Figma import** (free PAT, single frame) | 🟡 UI live-verified; **PAT round-trip never tested** | No Figma account available in the dev environment |
| **Stack Picker** (framework / language / API-style matrix) | ✅ Live | Unit tests + live UI |
| Architecture generation | ✅ Live | End-to-end |
| **Code Generation** (8 frontend × 12 backend adapters) | ✅ Live | 96 REST pairings smoke-tested; real `cargo check` and Angular CLI scaffold validation |
| **Testing phase** (stack-aware recipes, 20 frameworks) | ✅ Built | Recipes + 6 result parsers verified against real / realistic fixtures |
| **Export** (ZIP + README) | ✅ Live | Unit-tested |
| **Packaging / installers** | 🟡 Mixed — see §5 | |
| **Admin panel** | ✅ Live (desktop + mobile) | Playwright against the real DB: user list, detail, projects, suspend/ban, audit trail |
| **Marketplace** | 🟡 Backend API + desktop screens exist; no payment wiring | Not end-to-end tested |

### Codegen coverage — the honest limits

- **REST: all 96 pairings** (8 frontends × 12 backends) are buildable.
- **GraphQL: not implemented for any backend.**
- **gRPC: NestJS only.** `spring_boot` and `aspnet_core` declare it in the matrix but have no builder — those combos silently downgrade via `find_nearest()`.
- **SwiftUI** ships loose `.swift` files + a README only (no manifest, no CI).
- Always check `BUILDABLE_NOW` in `app/ai/stack_matrix.py` (it is computed, not hardcoded) before claiming a combination works.

---

## 4. AI Model System

Substantially rebuilt since the last update. Current architecture:

- **Providers:** `groq`, `openai`, `anthropic`, `xai` (Grok), `custom` (OpenAI-compatible endpoint), `portable` (USB-drive local models), plus the legacy env-configured Ollama/Groq fallback.
- **Model bag + priority chain:** users and admins register multiple configs; `orchestrator.generate_text()` walks them in `ai_bag_order`. A BYO user never silently falls back to platform Groq/Ollama.
- **Wired end-to-end** — every generation phase (wizard / requirements / uiux / architecture / codegen / testing / chat) passes `user` and `db` through. This was a real bug fixed 2026-07-26: previously only `POST /ai/ask` honored user config.
- **Task-aware routing:** `UserAIConfig.task_type` = `codegen` | `general` | NULL (any). All 24 codegen adapters funnel through the single `generate_text_validated()` call site.
- **Token metering + quota:** real prompt/completion token capture from Ollama, OpenAI-compatible providers, and Anthropic. `User.ai_tokens_used` / `ai_tokens_limit` (`-1` = unlimited), free tier = 200,000. **Only platform-default calls are metered** — BYO keys and self-hosted GPUs are never metered or blocked.
- **Known hole:** quota only engages when platform-default rows (`user_id IS NULL`) exist in `user_ai_configs`. Delete them all and it falls through to the unmetered legacy env path.
- **⚠️ Postgres migration unverified:** the `init_db()` auto-column migration for `ai_tokens_used` / `ai_tokens_limit` / `task_type` was only exercised against SQLite. If a pre-fix build ever ran against the live Supabase Postgres, run:

  ```sql
  UPDATE users SET ai_tokens_limit = 200000 WHERE ai_tokens_limit = 0;
  ```

  (An earlier `default=0` would have locked existing accounts out of all platform AI generation. The migration is idempotent and will not retro-fix them.)
- **Not built:** payment / purchase wiring. This is quota *tracking* only — "buy more tokens" does not exist. No `Transaction` model, not even a stub.
- **Not deployed:** the fine-tuned Qwen2.5-Coder on rented GPU (RunPod serverless was the recommendation). Once deployed, an admin just tags it `task_type="codegen"` in the AI Models screen — no code changes needed.

**Groq free tier:** 100,000 tokens/day. Still the practical constraint on heavy testing days.

---

## 5. Generation & Packaging Pipelines (18 workflows)

### Per-project app generation — 10 pipelines

| Target | Workflow | Status |
|---|---|---|
| Android (Capacitor WebView wrap) | `build-android-installer.yml` | ✅ **Confirmed live** — run 29668640261 (2026-07-19) produced a real 3.3 MB APK |
| Windows (Tauri WebView wrap) | `build-windows-installer.yml` | ✅ Template proven across 5 consecutive successful runs |
| Linux (Tauri WebView wrap) | `build-linux-installer.yml` | 🟡 Same template, its own runs unconfirmed |
| Android native — Jetpack Compose | `build-android-native-compose.yml` | 🟡 Never triggered |
| Android native — Flutter | `build-android-native-flutter.yml` | 🟡 Never triggered |
| Windows / Linux native — Flutter | `build-{windows,linux}-native-flutter.yml` | 🟡 Never triggered |
| Android / Windows / Linux game — Godot | `build-{android,windows,linux}-game-godot.yml` | 🟡 Never triggered |

- APK builds are **debug-signed** unless 4 GitHub secrets are set (`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`) — **nobody has generated these yet**, so every APK today is sideload-only.
- Exported code ships a README stating it is a **starter skeleton**, not a finished app.
- `o3de` and `swiftui` return 400 from `_workflow_for_stack()` — export-ZIP only, by design.

### O3DE — 2 pipelines

`package-o3de-project.yml` + `validate-o3de-template.yml`. Codegen was rewritten 2026-07-25 with real engine formats (the previous version was broken). Validate and zip only — no full engine build (10–20 GB, hours).

### VengaiCode's own product builds — 3 pipelines

| Target | Workflow | Status |
|---|---|---|
| Windows desktop `.msi` / `.exe` | `build-desktop-windows.yml` | ✅ **Builds work** — but only ever run **locally**; the workflow has 0 runs |
| Linux `.deb` / AppImage | `build-desktop-linux.yml` | 🟡 0 runs, untested |
| Own Android APK | `build-android-apk.yml` | ✅ Builds work via **EAS CLI directly**; the workflow has 0 runs and needs `EAS_TOKEN` / `EXPO_TOKEN` secrets |

- **macOS is still blocked** — `apps/desktop/src-tauri/icons/icon.icns` is a 0-byte stub and no code-signing setup exists.
- ⚠️ `apps/desktop/.env` has `VITE_API_URL=http://localhost:8000`, which is **baked in at build time**. Locally-built installers point at localhost, not Render. Change this before shipping a real installer.

### Quality gates — 2 workflows

- `backend-ci.yml` — ruff check + pytest on `apps/backend/**`. ✅ Confirmed passing live (run 30126818410).
- `run-tests.yml` — ~32 gated steps covering a generated project's own test suite across all 20 frameworks.

---

## 6. Configured but NOT Wired

Env vars and config exist; **zero code references**. Do not assume these work.

| Service | Intent |
|---|---|
| **Razorpay** | Payments + commissions (10% marketplace / 25% external / 10% template) |
| **Resend** | Transactional email (`support@vengaicode.com`) |
| **MeiliSearch** | Marketplace search |
| **Digio** | Identity verification / KYC |
| **Sentry** | Error tracking |
| **Cloudflare R2** | Superseded by Supabase Storage |

Commented-out routers in `api/v1/router.py`: `/licences`, `/payments`, `/users`, `/templates`, `/webhooks`.

Also written but never run: `docker-compose.prod.yml` (self-hosted Postgres + backups, to move off Supabase) and `docker-compose.yml` (full local stack — Postgres, Redis, Ollama, MeiliSearch, Gitea, Woodpecker, SonarQube, Prometheus, Grafana, Mailpit, Adminer). Neither has ever been started — no Docker on this machine.

---

## 7. Known Gaps & Risks

1. **Render's `GROQ_DEFAULT_MODEL` still holds the retired `llama-3.3-70b-versatile`** — now **defused, not fixed**: `Settings.substitute_retired_groq_models()` refuses a decommissioned id from any source and substitutes the current replacement, so the stale env var is inert. Clearing it in the dashboard is cosmetic; the only reason to care is that the startup log will keep warning about it.
2. **Render's `GITHUB_REPO` must be `rajesh22wolverine/VengaiCodes`** — an old `KalRaj2` value would silently break all packaging dispatches. Cannot be verified from here (no Render API key locally); confirm in the Render dashboard.
3. **AI token quota migration never run against Postgres** — see §4 for the `UPDATE` statement.
4. **Android release-signing secrets do not exist** — all APKs are debug-signed.
5. **`gh` CLI is unauthenticated** — cannot dispatch or inspect workflow runs.
6. **`apps/desktop/.env` points at localhost** — baked into any locally built installer.
7. **No payment path anywhere** — quota, pricing tiers, and commission rates are all defined but nothing can be purchased.
8. **`eslint` is inert** — `.eslintrc.js` is a 0-byte file and fails to parse. `ruff-format` is deliberately not enabled (it would reformat 58 of 78 backend files).
9. **`.husky/pre-commit` was never created** — the root `lint-staged` config is inert. `.pre-commit-config.yaml` is the mechanism actually working, and only after a dev runs `pip install pre-commit && pre-commit install`.
10. **Only 2 backend unit test files exist** (`test_export.py`, `test_stack_matrix_adapters.py`). Coverage is thin.
11. **Untracked `local_dev.db.backup-presession`** — add `*.db.backup-*` to `.gitignore`.

---

## 8. Dev Environment Notes

- **No Redis locally** → every API request takes roughly 4 s extra (the rate-limit check times out), about 8 s per GET once the CORS preflight is counted. Pad Playwright `waitForSelector` timeouts to 30 s; do not use short fixed sleeps.
- **Python execution quirk:** copy the interpreter into the scratchpad to run it; for real imports use a standalone `.py` with `PYTHONPATH` pointing at `apps/backend/venv` site-packages.
- **`ruff` and `pytest` are not installed** in `apps/backend/venv` — lint and tests only run in CI.
- **Outbound HTTPS is blocked** in the agent sandbox, so live backend health cannot be checked from a tool call.
- **EAS build status** must be polled with `eas build:view <id> --json` — the CLI's foreground log goes silent while a build sits `IN_QUEUE`.
- **`npx eas` fails** — the package is `eas-cli`; invoke it as `npx eas-cli@latest <cmd>`.

---

## 9. Recurring Bug Lessons

Patterns that have bitten more than once — check these first when something behaves oddly:

1. **JSON column in-place mutation is not tracked by SQLAlchemy.** `project.requirements_data["k"] = v` does nothing. Reassign: `project.requirements_data = {**d, "k": v}`.
2. **String vs Enum member mismatch.** `current_phase = "architecture"` instead of `SDLCPhase.ARCHITECTURE` silently breaks phase routing.
3. **Duplicate index definitions** (`index=True` plus an explicit `Index()`) crash `create_all()`. Indexes are created via raw `CREATE INDEX IF NOT EXISTS` in `main.py`'s lifespan instead.
4. **Any new AI-calling code path must call `generate_text()`** and pass `user` / `db` (or `ctx.user` / `ctx.db`) from day one — otherwise it silently ignores BYO config, quota, and task routing.
5. **New quota/limit columns:** check what `init_db()`'s ALTER TABLE backfills onto *existing* rows. The model default is not just a fresh-row concern.
6. **Recipe and label lookups must be scoped by `(framework_key, label)`** — labels like "pytest" and "cargo test" collide across frameworks and will silently shadow each other.
7. **`asyncpg` ignores `?sslmode=require`** in the URL. SSL comes from `connect_args={"ssl": "require"}` in `database.py`. Never suggest the query-param fix here.
8. **A missing `postcss.config.js`** once caused every screen in the app to render unstyled. One file.

---

## 10. Test Credentials (dev only)

Pattern: `rajesh22wolverine+SUFFIX@gmail.com` (Gmail `+` trick, all land in the same inbox), password `BabyTiger@123` or similar. Known accounts: `kalkitiger`, `kalkitiger4`, `kalkitest2-4`, `quotachecktest1`.

`rajesh22wolverine@gmail.com` is set `is_admin=True` in `apps/backend/local_dev.db`. SQLite-era users were wiped in the Supabase migration; only Postgres-era signups persist.

---

## 11. Next Candidates

- Verify Render's `GITHUB_REPO` (the `GROQ_DEFAULT_MODEL` env var is now inert — see §7.1).
- Run `gh auth login` so CI can be dispatched and inspected.
- Trigger one native pipeline (Compose or Flutter) for real — 7 of the 10 generation pipelines have never executed.
- Generate the Android release-signing secrets.
- Live-test the Figma PAT round-trip with a real account.
- Decide on payments: Razorpay is fully configured and connected to nothing.
- Deploy the fine-tuned coder model (RunPod serverless), then tag it `task_type="codegen"`.
- Fill in `apps/admin` and `apps/marketplace`, or delete the empty skeletons.
