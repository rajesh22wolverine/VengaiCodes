"""
End-to-end test of the deterministic (no-AI) Gin backend — nothing is
mocked. The generated project is written to a temp folder, tidied, checked
with gofmt and go vet, compiled with the real Go toolchain and run as a
real server on a real SQLite file, through the scenario every generated
backend goes through (generated_backend_e2e.py): the REST contract, a
schema change against the same database, a column drop, revert and
re-apply.

Needs `go` on PATH (and the network, once, for `go mod tidy`). Without it
these tests are skipped — unless VENGAI_REQUIRE_TOOLCHAINS lists "go",
which the backend CI job sets so a missing toolchain can't pass as a skip.
"""

import os

import generated_backend_e2e as e2e


def _backend() -> e2e.Backend:
    go = e2e.toolchain("go")

    def build(folder: str) -> None:
        # What the README says to do after generating or regenerating:
        # `go mod tidy` (a regenerated go.mod lists only what the code
        # imports), then build.
        e2e.run([go, "mod", "tidy"], folder)
        e2e.run([go, "build", "-o", f"app{e2e.EXE}", "."], folder)

    def first_build_checks(folder: str) -> None:
        unformatted = e2e.run(["gofmt", "-l", "."], folder).strip()
        assert not unformatted, "gofmt would change:\n" + e2e.run(
            ["gofmt", "-d", "."], folder
        )
        e2e.run([go, "vet", "./..."], folder)
        # The exact command the installer workflows build the desktop sidecar with.
        e2e.run([go, "build", "-o", f"dist_go/backend{e2e.EXE}", "main.go"], folder)

    return e2e.Backend(
        key="gin",
        error_key="error",
        tool="sqlite-go",
        sources=(".go", ".sql"),
        build=build,
        command=lambda folder: [os.path.join(folder, f"app{e2e.EXE}")],
        first_build_checks=first_build_checks,
    )


def test_generated_gin_app_builds_runs_and_migrates_a_real_database(tmp_path):
    e2e.run_lifecycle(_backend(), tmp_path)


def test_generated_gin_app_compiles_with_awkward_names(tmp_path):
    e2e.build_awkward_names(_backend(), tmp_path)
