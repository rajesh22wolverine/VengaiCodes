# Registers this O3DE project with your local engine install. This is the
# real first step for any hand-authored O3DE project - confirmed against
# the engine's own CLI (scripts/o3de/o3de/register.py in the o3de/o3de
# repo), unlike this script's previous version, which called
# `o3de project --generate` / `o3de asset build` / `o3de build --platform`
# - none of which are real o3de CLI subcommands.
#
# There is deliberately no unattended "build" step after this: O3DE's own
# export tooling (`o3de export-project`) requires a project-specific
# --export-script, and getting a project into a compilable state the
# first time normally happens through the Editor (Project Manager builds
# it on first open), not a one-shot CLI command. See README.md.

param(
    [string]$ProjectPath = ".",
    [string]$EnginePath = $env:O3DE_ENGINE_PATH
)

if (-not $EnginePath) {
    Write-Error "O3DE_ENGINE_PATH is not set. Set it to the root of your O3DE engine installation."
    exit 1
}

$o3deCmd = Join-Path $EnginePath "bin\o3de.cmd"
if (-not (Test-Path $o3deCmd)) {
    Write-Error "Could not find o3de.cmd at $o3deCmd. Verify your O3DE engine installation."
    exit 1
}

Write-Host "Using O3DE engine at: $EnginePath"
Write-Host "Registering O3DE project at: $ProjectPath"

& $o3deCmd register --project-path "$ProjectPath"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to register the project."
}

Write-Host "Registered. Open O3DE's Project Manager to build and open this project in the Editor."
