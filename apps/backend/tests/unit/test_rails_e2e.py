"""
End-to-end test of the deterministic (no-AI) Rails backend — nothing is
mocked. The generated app is written to a temp folder, its gems installed,
its Active Record migrations run with `rails db:migrate`, and it is served by
`rails server` on a real SQLite file, through the scenario every generated
backend goes through (generated_backend_e2e.py): the REST contract, a schema
change against the same database, a column drop, `rails db:rollback` of the
whole history and re-applying it.

Also here: the two name lists the generator refuses tables and fields by
(codegen_rails.RESERVED_CONSTANTS / RESERVED_ATTRIBUTES) are compared with
what a booted app really defines, so they can't quietly fall behind a Rails
release.

Needs `ruby` and `bundle` on PATH (and the network, once, for the gems).
Without them these tests are skipped — unless VENGAI_REQUIRE_TOOLCHAINS lists
"ruby", which the backend CI job sets so a missing toolchain can't pass as a
skip.
"""

import json
import os

import generated_backend_e2e as e2e
from test_deterministic_migrations_e2e import SHOP, FakeProject

from app.ai import codegen_deterministic as dc
from app.ai import codegen_rails, db_schema
from app.ai.migrations_rails import _VERSION_EPOCH


def _backend() -> e2e.Backend:
    e2e.toolchain("ruby")
    bundle = e2e.toolchain("ruby", "bundle")
    rails = [bundle, "exec", "rails"]

    def build(folder: str) -> None:
        e2e.run([bundle, "install"], folder, timeout=1800)

    def prepare(folder: str, env: dict) -> None:
        # What the README says to do after generating or regenerating.
        e2e.run([*rails, "db:migrate"], folder, timeout=300, env=env)
        # A server that was killed leaves its pid file behind.
        stale = os.path.join(folder, "tmp", "pids", "server.pid")
        if os.path.exists(stale):
            os.remove(stale)

    def applied(database: str) -> list[int]:
        return [
            int(version) - _VERSION_EPOCH
            for (version,) in e2e.query(
                database, "select version from schema_migrations order by version"
            )
        ]

    return e2e.Backend(
        key="rails",
        error_key="error",
        tool="rails",
        sources=(".rb", ".ru", ".yml"),
        build=build,
        command=lambda folder: [*rails, "server", "--binding", "127.0.0.1"],
        prepare=prepare,
        revert=lambda folder: [*rails, "db:rollback"],
        applied=applied,
        bookkeeping=frozenset({"schema_migrations", "ar_internal_metadata"}),
        migrations=("backend/db/migrate/", ".rb"),
        runs_in_project=True,
    )


def test_generated_rails_app_runs_and_migrates_a_real_database(tmp_path):
    e2e.run_lifecycle(_backend(), tmp_path)


def test_generated_rails_app_runs_with_awkward_names(tmp_path):
    e2e.build_awkward_names(_backend(), tmp_path)


# What Active Record generates for a column "x" besides x itself: a column
# may not be named so that any of these already exists on a record.
_PROBE = """
constants = Object.constants.map(&:to_s)
dangerous = ActiveRecord::AttributeMethods.dangerous_attribute_methods.to_a
patterns = ActiveRecord::Base.attribute_method_patterns.map { |p| [p.prefix, p.suffix] }
taken = dangerous.flat_map do |name|
  patterns.filter_map do |prefix, suffix|
    next unless name.start_with?(prefix) && name.end_with?(suffix)
    next if name.length < prefix.length + suffix.length
    name[prefix.length...(name.length - suffix.length)]
  end
end
puts JSON.generate(constants: constants, attributes: taken.uniq)
"""


def test_rails_reserved_names_match_what_a_booted_app_defines(tmp_path):
    backend = _backend()
    data = dc.build_deterministic_codegen_data(FakeProject(SHOP), e2e.stack("rails"))
    folder = e2e.write_backend(data, tmp_path, backend.sources)
    backend.build(folder)
    with open(os.path.join(folder, "probe.rb"), "w", encoding="utf-8") as f:
        f.write(_PROBE)
    output = e2e.run(
        ["bundle", "exec", "rails", "runner", "probe.rb"],
        folder,
        timeout=300,
        env=e2e.app_env(str(tmp_path / "app.db")),
    )
    found = json.loads(output.strip().splitlines()[-1])

    # A table's class name has no underscore, so only such constants matter;
    # the app's own models and controllers are not Ruby's or Rails'.
    own = {t.class_name for t in db_schema.resolve_schema(SHOP, backend="rails").tables}
    constants = {
        name
        for name in found["constants"]
        if "_" not in name and name not in own and not name.endswith("Controller")
    }
    reserved = codegen_rails.RESERVED_CONSTANTS | codegen_rails._OWN_CONSTANTS
    missing_constants = sorted(constants - reserved)

    # A column name is a lower-case identifier ("id" is every table's own).
    attributes = {
        name
        for name in found["attributes"]
        if name
        and name == name.lower()
        and name.replace("_", "").isalnum()
        and name[0].isalpha()
    }
    missing_attributes = sorted(attributes - codegen_rails.RESERVED_ATTRIBUTES - {"id"})
    # Exact in both directions: a name Active Record allows shouldn't be refused.
    # (Constants are only checked one way — some load later, e.g. in a console.)
    extra_attributes = sorted(codegen_rails.RESERVED_ATTRIBUTES - attributes)
    assert not (missing_constants or missing_attributes or extra_attributes), (
        "\nadd to codegen_rails.RESERVED_CONSTANTS: "
        + " ".join(missing_constants)
        + "\nadd to codegen_rails.RESERVED_ATTRIBUTES: "
        + " ".join(missing_attributes)
        + "\nremove from codegen_rails.RESERVED_ATTRIBUTES: "
        + " ".join(extra_attributes)
    )
