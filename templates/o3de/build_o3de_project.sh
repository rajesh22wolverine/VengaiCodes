#!/usr/bin/env bash
set -euo pipefail

# Registers this O3DE project with your local engine install. This is the
# real first step for any hand-authored O3DE project — confirmed against
# the engine's own CLI (scripts/o3de/o3de/register.py in the o3de/o3de
# repo), unlike this script's previous version, which called
# `o3de project --generate` / `o3de asset build` / `o3de build --platform`
# — none of which are real o3de CLI subcommands.
#
# There is deliberately no unattended "build" step after this: O3DE's own
# export tooling (`o3de export-project`) requires a project-specific
# `--export-script`, and getting a project into a compilable state the
# first time normally happens through the Editor (Project Manager builds
# it on first open), not a one-shot CLI command. See README.md.

PROJECT_PATH="${1:-.}"
ENGINE_PATH="${O3DE_ENGINE_PATH:-}"

if [[ -z "$ENGINE_PATH" ]]; then
  echo "O3DE_ENGINE_PATH is not set. Set it to the root of your O3DE engine installation." >&2
  exit 1
fi

O3DE_CMD="$ENGINE_PATH/bin/o3de"
if [[ ! -x "$O3DE_CMD" ]]; then
  echo "Could not find executable o3de at $O3DE_CMD. Verify your O3DE engine installation." >&2
  exit 1
fi

echo "Using O3DE engine at: $ENGINE_PATH"
echo "Registering O3DE project at: $PROJECT_PATH"

"$O3DE_CMD" register --project-path "$PROJECT_PATH"

echo "Registered. Open O3DE's Project Manager to build and open this project in the Editor."
