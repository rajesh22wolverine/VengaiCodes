"""
End-to-end test of the deterministic (no-AI) ASP.NET Core backend — nothing
is mocked. The generated project is written to a temp folder, built with the
real .NET SDK (warnings are errors) and run as a real server on a real
SQLite file, through the scenario every generated backend goes through
(generated_backend_e2e.py): the REST contract, a schema change against the
same database, a column drop, revert and re-apply.

Needs `dotnet` on PATH (and the network, once, to restore packages). Without
it these tests are skipped — unless VENGAI_REQUIRE_TOOLCHAINS lists
"dotnet", which the backend CI job sets so a missing toolchain can't pass as
a skip.
"""

import os

import generated_backend_e2e as e2e

from app.ai import codegen_aspnet


def _backend() -> e2e.Backend:
    dotnet = e2e.toolchain("dotnet")

    def build(folder: str) -> None:
        # NuGetAudit off: a vulnerability published tomorrow for a pinned
        # package is a warning about the package, not about this code.
        e2e.run(
            [
                dotnet,
                "build",
                "--configuration",
                "Release",
                "--nologo",
                "-warnaserror",
                "-p:NuGetAudit=false",
            ],
            folder,
            timeout=1500,
        )

    def command(folder: str) -> list[str]:
        return [
            dotnet,
            os.path.join(
                folder,
                "bin",
                "Release",
                codegen_aspnet.TARGET_FRAMEWORK,
                f"{codegen_aspnet.NAMESPACE}.dll",
            ),
        ]

    return e2e.Backend(
        key="aspnet_core",
        error_key="detail",
        tool="sqlite-cs",
        sources=(".cs", ".sql", ".csproj", ".json"),
        build=build,
        command=command,
    )


def test_generated_aspnet_app_builds_runs_and_migrates_a_real_database(tmp_path):
    e2e.run_lifecycle(_backend(), tmp_path)


def test_generated_aspnet_app_compiles_with_awkward_names(tmp_path):
    e2e.build_awkward_names(_backend(), tmp_path)
