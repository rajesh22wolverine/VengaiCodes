"""
End-to-end test of the deterministic (no-AI) Actix Web and Axum backends —
nothing is mocked. The generated crate is written to a temp folder, built
with the real Rust toolchain (warnings are errors) and run as a real server
on a real SQLite file, through the scenario every generated backend goes
through (generated_backend_e2e.py): the REST contract, a schema change
against the same database, a column drop, `revert` of the whole history and
re-applying it.

The compiled dependencies (sqlx with its bundled SQLite, tokio, actix-web /
axum) are kept in one Cargo target directory between runs
(generated_backend_e2e.cache_dir), so only the generated crate itself is
compiled each time. Every project generated here has the same crate name,
so each build replaces the last one's binary there — which is why a test
always builds the project it is about to run.

Needs `cargo` on PATH (and the network, once, for the crates). Without it
these tests are skipped — unless VENGAI_REQUIRE_TOOLCHAINS lists "rust",
which the backend CI job sets so a missing toolchain can't pass as a skip.
"""

import os
import re

import generated_backend_e2e as e2e
import pytest

FRAMEWORKS = ["actix", "axum"]


def _crate_name(folder: str) -> str:
    with open(os.path.join(folder, "Cargo.toml"), encoding="utf-8") as f:
        return re.search(r'^name = "([^"]+)"', f.read(), re.M).group(1)


def _backend(framework: str) -> e2e.Backend:
    cargo = e2e.toolchain("rust", "cargo")
    target = e2e.cache_dir("cargo-target")
    env = {
        **os.environ,
        "CARGO_TARGET_DIR": target,
        "CARGO_TERM_COLOR": "never",
        # No debug info: a fraction of the size, and nothing here needs it.
        "CARGO_PROFILE_DEV_DEBUG": "0",
        # Nor incremental state: every run is a new project in a new folder,
        # and each would leave its own behind in the shared directory.
        "CARGO_INCREMENTAL": "0",
        # A warning in generated code is a defect like any other.
        "RUSTFLAGS": "-D warnings",
    }

    def build(folder: str) -> None:
        e2e.run([cargo, "build"], folder, timeout=1800, env=env)

    def command(folder: str) -> list[str]:
        return [os.path.join(target, "debug", _crate_name(folder) + e2e.EXE)]

    return e2e.Backend(
        key=framework,
        error_key="detail",
        tool="sqlite-rs",
        sources=(".rs", ".sql", ".toml"),
        build=build,
        command=command,
        # sqlx reads a URL, with forward slashes even on Windows.
        env=lambda database: {
            "DATABASE_URL": "sqlite://" + database.replace("\\", "/")
        },
    )


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_generated_rust_app_builds_runs_and_migrates_a_real_database(
    framework, tmp_path
):
    e2e.run_lifecycle(_backend(framework), tmp_path)


@pytest.mark.parametrize("framework", FRAMEWORKS)
def test_generated_rust_app_compiles_with_awkward_names(framework, tmp_path):
    e2e.build_awkward_names(_backend(framework), tmp_path)
