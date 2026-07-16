# VengaiCode Mobile

This folder contains the Expo mobile scaffolding for Android/iOS APK builds.

## Commands

From the repo root:

- `pnpm install`
- `pnpm --filter @vengaicode/mobile android`
- `pnpm --filter @vengaicode/mobile build`
- `pnpm --filter @vengaicode/mobile start`

## GitHub Actions

This repo includes a workflow to build an Android APK via EAS:

- `.github/workflows/build-android-apk.yml`

It is triggered manually or by `repository_dispatch` with type `build-android-app`.

### Required secrets

- `EAS_TOKEN`
- `EXPO_TOKEN`

## Notes

- This package is configured for Expo SDK 49.
- Android APK support is enabled through `eas.json` with `buildType: "apk"`.
- Run `expo doctor` if you need to verify your local Expo SDK/environment.
