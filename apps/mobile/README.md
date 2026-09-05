# VengaiCode Mobile

This folder contains the Expo mobile scaffolding for Android/iOS APK builds.

## Commands

From the repo root:

- `pnpm install`
- `pnpm --filter @vengaicode/mobile android`
- `pnpm --filter @vengaicode/mobile build`
- `pnpm --filter @vengaicode/mobile start`

## GitHub Actions

This repo includes a workflow to build an Android APK with Gradle directly
on the runner — no Expo account and no EAS build queue:

- `.github/workflows/build-android-gradle.yml`

It is triggered manually (`workflow_dispatch`) and runs `expo prebuild` +
`gradlew` on `ubuntu-latest`, which already ships the Android SDK.

### Required secrets

None. The EAS-based workflow that needed `EAS_TOKEN` / `EXPO_TOKEN` was
removed — those secrets were never configured and its builds sat in
Expo's free-tier queue for hours.

Note: the APK is debug-signed and installable directly, but is **not**
Play Store-publishable. That needs a real upload keystore.

## Notes

- This package is configured for Expo SDK 49.
- Android APK support is enabled through `eas.json` with `buildType: "apk"`.
- Run `expo doctor` if you need to verify your local Expo SDK/environment.
