# VengaiCode — Project Status
Last updated: 2026-07-01 (after Sprint 5 backend/frontend built)

## Live Infrastructure
- **Backend:** https://vengaicode-backend.onrender.com (FastAPI, Python 3.11, Render free tier)
- **Database:** Supabase Postgres (session pooler, SSL required) — persistent, replaced SQLite
- **AI:** Groq (llama-3.3-70b-versatile) — cloud fallback, Ollama not running anywhere yet
- **Frontend dev environment:** GitHub Codespaces (local Windows machine has insufficient RAM
  for Docker/Ollama — Oracle Cloud signup blocked on debit card verification, unresolved)
- **Repo:** github.com/KalRaj2/VengaiCodes (private), auto-deploys to Render on push to `main`

## Sprint Status
| Sprint | Feature | Status |
|---|---|---|
| 1 | Auth (signup/OTP/login/forgot-password), Dashboard, Projects CRUD | ✅ Built & tested |
| 2 | 7-layer AI Wizard (conversational requirements gathering) | ✅ Built & tested |
| 3 | Requirements Document generation (AI → structured FRD JSON) | ✅ Built & tested |
| 4 | UI/UX Design generation (colors, typography, screens, components) | ✅ Built & tested |
| 5 | Architecture generation (tech stack, DB schema, API endpoints) | ✅ Built, NOT yet tested (saving Groq tokens) |
| 6 | Code Generation (planned, not built) | 📋 Planned only — see below |
| 7+ | Testing, Export, Marketplace | Not started |

## Known Working End-to-End Flow
Signup → Verify OTP → Login → Create Project → 7-Question Wizard → Approve Requirements
→ Approve UI/UX → (Sprint 5, untested) Approve Architecture → CodeGen placeholder

## Real Bugs Found & Fixed This Session
1. **Duplicate index/unique constraint definitions** in SQLAlchemy models (`index=True` on
   column + explicit `Index()` in `__table_args__` for same column) — caused SQLite/Postgres
   crashes on `create_all()`. Fixed by using `CREATE INDEX IF NOT EXISTS` raw SQL in `main.py`
   lifespan instead of relying on SQLAlchemy's index creation.
2. **JSON column in-place mutation not detected by SQLAlchemy** — `project.requirements_data["key"] = x`
   doesn't trigger change tracking; must reassign the whole dict:
   `project.requirements_data = {**dict, "key": x}`. Same pattern needed for any JSON column update.
   (Architecture endpoint already has this fix baked in from the start.)
3. **String vs Enum member mismatch** — `project.current_phase = "architecture"` (string) instead
   of `SDLCPhase.ARCHITECTURE` (enum) caused phase routing to silently fail, sending users back
   to the wizard instead of resuming where they left off.
4. **Missing `postcss.config.js`** — Tailwind directives in `globals.css` were never being
   processed at all, causing the entire app to render unstyled/congested. This was the root
   cause of ALL visual layout issues across every screen. One file fixed everything.
5. **Groq model deprecation** — `llama3-70b-8192` was decommissioned; switched to
   `llama-3.3-70b-versatile` via `GROQ_DEFAULT_MODEL` env var on Render.
6. Various: OAuth2 Swagger auth setup, CORS for rotating Codespaces URLs (now `allow_origins=["*"]`
   in development mode), Redis calls needed try/except fail-open wrapping throughout
   (no Redis service on Render free tier — everything degrades gracefully).

## Groq Free Tier Constraint
100,000 tokens/day limit. Heavy testing (wizard + requirements + uiux regenerated multiple
times while debugging) exhausts this within a few hours of active development. Resets daily.
Consider: (a) second Groq account for dev, or (b) Oracle Cloud VM running local Ollama once
card verification is resolved, to remove this constraint entirely.

## Sprint 6 Plan (Code Generation) — drafted, not built
- Realistic scope: generate a runnable code SKELETON (SQLAlchemy models from architecture's
  database_tables, FastAPI route stubs from api_endpoints, React component shells from
  uiux screens) — NOT a finished app. Testing/Export phases refine and package it later.
- Files needed: `apps/backend/app/api/v1/codegen.py`, router wiring, `CodeGenScreen.tsx`
  (file tree + syntax-highlighted preview + approve button)
- Open question: single large AI JSON response (risk: token truncation) vs. one file per
  AI call (more reliable, more tokens spent) — decide when testing resumes.

## Pending / Deferred
- Frontend polish pass: mobile/narrow-window responsiveness, empty states (Pending/Completed
  tabs with zero items), invalid/foreign project ID error handling — not yet tested.
- Optional cleanup: split `schemas/requirements.py` out of `api/v1/requirements.py` for
  consistency with other modules (zero functional benefit, purely organizational — low priority).
- Oracle Cloud Free Tier signup — blocked on debit card verification (declined twice,
  likely RuPay network or international-transactions-disabled issue). Alternative: try a
  different bank's Visa/Mastercard debit card, or a virtual card service like Niyo Global.

## Test Credentials (dev/testing only)
Various test accounts created during debugging (kalkitiger, kalkitiger4, kalkitest2-4, etc.)
— pattern: `rajesh22wolverine+SUFFIX@gmail.com` (Gmail + trick, all land in same real inbox),
password pattern `BabyTiger@123` or similar. SQLite-era test users were wiped when migrated
to Supabase Postgres; only Postgres-era signups (post Sprint 4 debugging) persist permanently.
