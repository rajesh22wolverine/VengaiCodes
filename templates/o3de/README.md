# VengaiCode O3DE Template

A real, minimal Open 3D Engine (O3DE) project scaffold: a valid
`project.json`, one level (`Levels/Main/Main.prefab`) with one entity
running a real Lua behavior script (`Scripts/main.lua`).

This replaces an earlier version of this template that used a fabricated
`ProjectName.project`/`ProjectName.workspace` XML format and CLI commands
(`o3de project --generate`, `o3de asset build`, `o3de build --platform`)
that don't exist in real O3DE. Every file here was checked against O3DE's
own open-source repo (github.com/o3de/o3de) — real `project.json` schema,
real prefab JSON shape, real Lua script structure, and the real `o3de`
CLI subcommand list (`scripts/o3de/o3de/*.py`).

## What is included

- `project.json` — a real O3DE project descriptor.
- `Levels/Main/Main.prefab` — a real level with one entity and a Lua
  Script component pointing at `Scripts/main.lua`.
- `Scripts/main.lua` — a real, syntactically valid Lua component script
  (TickBus heartbeat example).
- `build_o3de_project.sh` / `.ps1` — registers this project with a local
  O3DE engine install (`o3de register --project-path .`).

## What is NOT included, and why

- **No engine binaries.** This repo does not bundle O3DE — install it
  yourself from https://o3de.org/download.
- **No automated build/export.** O3DE's own export tooling
  (`o3de export-project`) needs a project-specific `--export-script`;
  the normal way to get a fresh project into a working state is opening
  it in the Editor via Project Manager (which builds it on first open),
  not a single CLI command. This is a genuine O3DE workflow constraint,
  not something this template is cutting a corner on.
- **One manual script re-link.** The Lua Script component's asset
  reference can supply the correct file path but not a real Asset
  Processor-assigned ID ahead of time — open `Main.prefab` in the
  Editor, select the entity, and browse to `Scripts/main.lua` in the
  Script component once. The Editor resolves and re-saves it from then
  on.

## How to use

1. Install O3DE and set `O3DE_ENGINE_PATH` to your engine install root.
   - Windows: `setx O3DE_ENGINE_PATH "C:\Path\To\O3DE"`
   - Linux/macOS: `export O3DE_ENGINE_PATH="/path/to/o3de"`
2. Run the register script from this folder:
   - Windows: `.\build_o3de_project.ps1 -ProjectPath .`
   - Linux/macOS: `./build_o3de_project.sh .`
3. Open O3DE's Project Manager, find this project in your registered
   list, and open it (builds the Editor the first time — takes a while).
4. Do the one-time script re-link described above, then use the
   Editor's own Export/Game Export workflow for a platform build.

See VengaiCode's own generated O3DE projects for the same shape, scaled
up to one entity+script per feature — this template is the minimal
reference, not a generated project itself.
