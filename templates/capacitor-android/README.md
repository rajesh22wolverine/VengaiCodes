# VengaiCode — Capacitor Android Template

Wraps a generated web frontend as an installable Android APK using
[Capacitor](https://capacitorjs.com/). Mirrors how `templates/tauri-windows`
wraps the same kind of frontend as a Windows desktop app.

## How it's used

This template is **not** built directly — `build-android-installer.yml`
copies it into a `build/` working directory, injects the AI-generated
project's `frontend/` files on top of it, merges `package.json` so the
Capacitor/Vite/Tailwind tooling here survives the injection, then:

1. `npm install`
2. `npx cap add android` — generates the native Android project fresh
   from the installed `@capacitor/android` package (not checked into
   this repo — it's regenerated on every build)
3. `npm run build` (Vite) + `npx cap sync android`
4. `cd android && ./gradlew assembleDebug` — produces a debug `.apk`

## Known limitations

- Produces a **debug** APK, not a signed release build. Installing it
  requires "unknown sources" to be enabled on the device; it is not
  suitable for Play Store submission as-is.
- Like the Windows path, this packages the generated **frontend** only
  — it does not bundle a working backend server.
- Untested end-to-end against a real Android SDK/Gradle toolchain in CI;
  expect to need a debugging pass on the first real run.
