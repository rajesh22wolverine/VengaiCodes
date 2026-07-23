# Session Summary — 2026-07-19

Features and fixes built in this working session, in the order they were tackled.

---

## 1. Native build pipelines (Windows, Linux, Android)

Three GitHub Actions workflows that take a user's AI-generated frontend and package it as a real installable app.

| Platform | Workflow | Output | Toolchain |
|---|---|---|---|
| Windows | `.github/workflows/build-windows-installer.yml` | `.msi` + `.exe` | Tauri (`templates/tauri-windows`) |
| Linux | `.github/workflows/build-linux-installer.yml` | `.deb` + `.AppImage` | Tauri (`templates/tauri-linux`) |
| Android | `.github/workflows/build-android-installer.yml` | `.apk` (debug) | Capacitor (`templates/capacitor-android`), native Android project generated fresh via `npx cap add android` rather than checked in |

**Bugs fixed along the way:**
- The Windows workflow was overwriting the Tauri template's `package.json` (which carries the `vite`/`tauri`/`tailwind` build tooling) with the AI-generated app's own `package.json`, silently dropping the tooling needed to build at all. Now merges instead of overwrites (`.github/scripts/merge_package_json.py`).
- Two inline Python heredocs in the Windows workflow were malformed (mixed YAML/Python indentation, would throw `IndentationError` or break YAML parsing). Moved all Python logic into real script files under `.github/scripts/`.
- The icon config (`tauri.conf.json`) referenced PNG/`.icns` files that never existed in the repo — would have failed bundling on **every** platform. Generated real placeholder PNG icons at the correct sizes for Windows, Linux, and the Android/Capacitor template.
- A duplicate router registration in `apps/backend/app/api/v1/router.py` (the Windows packaging router was included twice).

**Backend endpoints** (all under `/api/v1/packaging/*`, mirrored per platform): trigger build, poll status, list artifacts, download artifact — proxying GitHub Actions' `repository_dispatch` and artifacts API. Requires `GITHUB_TOKEN`, `GITHUB_REPO`, `BUILD_SECRET` configured on Render (not newly added by this session, but what these endpoints depend on).

**Frontend**: Export screen (`ExportScreen.tsx`) gained "Windows Installer", "Linux Installer", and "Android APK" cards — each with trigger → poll → download UX, all marked "Experimental."

**Known gaps**: none of the three workflows have actually executed on a real GitHub Actions runner (verified via static checks — YAML parses, Python compiles, routes resolve — not via a live run). Android produces a debug (unsigned) APK only.

---

## 2. O3DE game-template validation workflow

`.github/workflows/validate-o3de-template.yml` — runs on free GitHub-hosted runners, checks the `templates/o3de/` scaffold is structurally sound (required files present, XML parses, shell/PowerShell scripts are syntactically valid, placeholder Python compiles). Deliberately does **not** attempt a real O3DE engine build — that needs a self-hosted runner with O3DE installed (tens of GB, hours, ideally a GPU), which doesn't exist yet. Runner setup for real compilation was discussed but deferred by request.

---

## 3. Design-to-code: upload, camera, and voice

On the UI/UX phase screen, users can now provide their own page designs instead of relying only on the AI-generated design system.

- **Upload or capture**: file upload (PNG/JPEG/WebP) or a live camera capture (`getUserMedia` + canvas snapshot) — for photographing a sketch, whiteboard, or physical mockup.
- **Generate code**: the image is sent to Groq's hosted Llama 3.2 Vision model, which returns editable HTML + CSS matching the design.
- **Voice notes**: per-uploaded-design mic recording (`MediaRecorder`) — the raw audio is stored AND transcribed via Groq's hosted Whisper (`whisper-large-v3`); the transcript is folded into the next code-generation prompt as extra spoken instructions (e.g. "make the header sticky, use a blue theme").
- **Edit in place**: generated HTML/CSS is shown in editable text areas the user can tweak and save before it feeds into later phases.

**New backend infrastructure**:
- `app/core/storage.py` — Supabase Storage REST client (images in one subfolder, voice notes in another, same public bucket).
- `app/ai/orchestrator.py` gained `generate_vision()` (Groq vision) and `transcribe_audio()` (Groq Whisper) alongside the existing text-only `generate_text()`.
- New config: `GROQ_VISION_MODEL`, `GROQ_WHISPER_MODEL`, `SUPABASE_DESIGN_UPLOADS_BUCKET`. Requires `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` (previously dead config, now wired up) and a public `design-uploads` bucket in Supabase Storage — both set up during this session.

---

## 4. Marketplace (browse + list, no payments yet)

Resurrected `apps/marketplace/`'s empty scaffolding as real screens inside the existing desktop app instead of a separate Next.js project — reuses existing auth/DB/deploy rather than standing up new infrastructure.

- **Backend**: new `MarketplaceApp` model (resolves a previously-dangling relationship reference on `User`), routes to create/browse/search/view/edit/delete listings.
- **Frontend**: Browse screen (search + category filter + "My Listings" tab), listing detail screen, create-listing form. The sidebar's "Marketplace" link now goes to this in-app screen instead of opening `vengaicode.com` externally.
- Any authenticated user can list for now (`price` is stored/displayed but nothing charges it) — full seller verification and Razorpay checkout are explicitly deferred to a follow-up.

---

## 5. Cross-phase chat + requirement redefinition

Every phase screen (Requirements, UI/UX, Architecture, CodeGen, Testing, Export) now has a floating chat panel (`ChatPanel.tsx`) backed by one continuous conversation thread per project (`Project.chat_messages`).

- **General Q&A**: ask questions about the app at any point; the AI just replies.
- **Requirement changes**: if a message implies changing what the app should do (new feature, different platform, etc.), the AI returns a fully updated requirements document. The app merges it in, unapproves requirements, clears `phases_completed`, resets to the Requirements phase, and the frontend automatically navigates the user back there to review — later phases' prior output is kept (not deleted) but no longer marked complete, so the user redoes them deliberately rather than having them silently overwritten.
- Backend: `apps/backend/app/api/v1/chat.py`, one AI call per message that both classifies intent and (when relevant) produces the updated FRD in a single structured response.

---

## Net new config/environment variables introduced this session

| Variable | Purpose | Has a code default? |
|---|---|---|
| `GROQ_VISION_MODEL` | Design-image-to-code | Yes — `llama-3.2-90b-vision-preview` |
| `GROQ_WHISPER_MODEL` | Voice note transcription | Yes — `whisper-large-v3` |
| `SUPABASE_DESIGN_UPLOADS_BUCKET` | Storage bucket name | Yes — `design-uploads` |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Supabase Storage access | No — must be set (done this session) |
| `VENGAICODE_BUILD_SECRET` / `BUILD_SECRET` | Native build callback auth | No — required for packaging workflows to work at all |
| `GITHUB_TOKEN`, `GITHUB_REPO` | Trigger/poll GitHub Actions from the backend | No — required for packaging workflows |

## Verification performed (and its limits)

Every change in this session was checked with real tool runs, not just read-through:
- Python: `py_compile` on every new/changed backend file, plus full `from app.main import app` import checks confirming route registration and no path collisions.
- TypeScript: `tsc --noEmit` after every frontend change, zero errors introduced.
- YAML: `yaml.safe_load()` on every workflow file.
- JSON: parsed every generated `package.json`/`tauri.conf.json`/`capacitor.config.json`.
- Generated icon PNGs opened and measured to confirm correct dimensions.

**What was *not* verified** (couldn't be, without live credentials or a real CI run): no GitHub Actions workflow has executed end-to-end; no live Supabase Storage upload or Groq API call has been exercised; the marketplace and chat features haven't been driven through the actual running app in a browser/webview.
