"""
End-to-end test of the deterministic (no-AI) Laravel backend — nothing is
mocked. The generated app is written to a temp folder, its packages
installed with Composer, every PHP file it consists of compiled with
`php -l`, its migrations run with `php artisan migrate`, and it is served by
`php artisan serve` on a real SQLite file, through the scenario every
generated backend goes through (generated_backend_e2e.py): the REST
contract, a schema change against the same database, a column drop,
`php artisan migrate:rollback` of the whole history and re-applying it.

Needs `php` (with pdo_sqlite) and `composer` on PATH (and the network, once,
for the packages). Without them these tests are skipped — unless
VENGAI_REQUIRE_TOOLCHAINS lists "php", which the backend CI job sets so a
missing toolchain can't pass as a skip.
"""

import os
import re

import generated_backend_e2e as e2e

# A migration's name, as Laravel records it: its file name without .php.
_NUMBER = re.compile(r"^2024_01_01_(\d{6})_")


def _backend() -> e2e.Backend:
    php = e2e.toolchain("php")
    composer = e2e.toolchain("php", "composer")
    artisan = [php, "artisan"]

    def build(folder: str) -> None:
        e2e.run(
            [composer, "install", "--no-interaction", "--no-progress"],
            folder,
            timeout=1200,
        )

    def first_build_checks(folder: str) -> None:
        # Every PHP file of the app compiles (vendor/ is Composer's).
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d != "vendor"]
            for name in files:
                if name.endswith(".php") or name == "artisan":
                    e2e.run([php, "-l", os.path.join(root, name)], folder, timeout=60)

    def prepare(folder: str, env: dict) -> None:
        # What the README says to do after generating or regenerating;
        # --force creates the database file instead of asking.
        e2e.run(
            [*artisan, "migrate", "--force", "--no-interaction"],
            folder,
            timeout=300,
            env=env,
        )

    def applied(database: str) -> list[int]:
        return [
            int(_NUMBER.match(name).group(1))
            for (name,) in e2e.query(
                database, "select migration from migrations order by migration"
            )
        ]

    return e2e.Backend(
        key="laravel",
        error_key="message",
        tool="laravel",
        sources=(".php",),
        build=build,
        command=lambda folder: [
            *artisan,
            "serve",
            "--host=127.0.0.1",
            "--port={port}",
            "--no-reload",
        ],
        first_build_checks=first_build_checks,
        prepare=prepare,
        revert=lambda folder: [
            *artisan,
            "migrate:rollback",
            "--step=1",
            "--force",
            "--no-interaction",
        ],
        applied=applied,
        bookkeeping=frozenset({"migrations"}),
        migrations=("backend/database/migrations/", ".php"),
        runs_in_project=True,
    )


def test_generated_laravel_app_runs_and_migrates_a_real_database(tmp_path):
    e2e.run_lifecycle(_backend(), tmp_path)


# Named like the classes the app is made of (a model App\Models\Controller
# beside the base controller; models called ApiError and RequestFields beside
# the App\Support classes), with fields named like Eloquent's own methods and
# settings, which a model must never mistake for its columns. "Migration" is
# refused: its table would be Laravel's own `migrations`.
LARAVEL_AWKWARD_TABLES = [
    {
        "name": "Controller",
        "key_fields": ["save", "delete", "fresh", "touch", "push", "with"],
    },
    {
        "name": "Api Error",
        "key_fields": ["date_format", "primary_key", "key_type", "per_page"],
    },
    {
        "name": "Request Fields",
        "key_fields": ["fill", "row", "parse", "shown", "controller_id"],
        "foreign_keys": [{"field": "controller_id", "references_table": "Controller"}],
    },
    {"name": "Migration", "key_fields": ["up", "down", "within_transaction"]},
]


def test_generated_laravel_app_runs_with_awkward_names(tmp_path):
    e2e.build_awkward_names(_backend(), tmp_path, LARAVEL_AWKWARD_TABLES)
