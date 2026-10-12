# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Laravel migrations for the deterministic Laravel backend
#  ai/migrations_laravel.py — Renders one revision (bookkeeping, history
#  and safety rules are migrations_gen's) as a real Laravel migration,
#  database/migrations/2024_01_01_00000N_<name>.php: `php artisan
#  migrate` applies it, `php artisan migrate:rollback` undoes it, and
#  Laravel records it in its own `migrations` table.
#
#  The migration's body is SQL, not the schema builder, on purpose:
#    - The schema builder has no CHECK constraint, and SQLite can only
#      take one when the table is created — so a generated table's rules
#      could not be expressed in it at all.
#    - SQLite changes a column by rebuilding its table. The SQL here is
#      migrations_sqlite's (the statements the Rust, Go and C# backends
#      run, already exercised against real databases), so a rebuild
#      keeps every constraint, index and row.
#
#  And with foreign keys on, dropping the old table of a rebuild deletes
#  the rows that point at it. The switch that prevents it is ignored
#  inside a transaction, and Laravel runs a SQLite migration inside one
#  — so every migration here sets $withinTransaction = false and opens
#  its own transaction between Schema::disableForeignKeyConstraints()
#  and enableForeignKeyConstraints().
#
#  The SQL sits in a nowdoc (<<<'SQL'), which PHP reads literally; its
#  closing marker is chosen so no line of the SQL can end it early.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import re

from app.ai import migrations_sqlite


def name(rev_id: str, slug: str) -> str:
    return "initial_schema" if int(rev_id) == 1 else slug


def filename(rev_id: str, slug: str) -> str:
    """Laravel orders migrations by file name; the prefix is its usual
    date-and-time shape with the revision's number as the time."""
    return f"backend/database/migrations/2024_01_01_{int(rev_id):06d}_{name(rev_id, slug)}.php"


def comment(text: str) -> str:
    """User text on one `//` line: `?>` would end PHP even inside a comment."""
    line = " ".join(str(text or "").split())
    line = "".join(ch for ch in line if ch.isprintable())
    return line.replace("?>", "? >").replace("TODO", "to-do")


def _nowdoc(statements: list[str]) -> list[str]:
    # "TODO" can only be inside a quoted value here; written as two halves
    # joined by SQL, it is the same value and no longer looks like a marker
    # left in generated code.
    sql = "\n".join(statements).replace("TODO", "TO' || 'DO")
    marker = "SQL"
    while re.search(rf"^\s*{marker}\b", sql, re.M):
        marker += "_"
    return [f"        $this->runStatements(<<<'{marker}'", sql, f"{marker});"]


def render_revision(rev: dict, down_id: str | None, previous_snapshot: dict) -> str:
    snap = rev["snapshot"]
    title = (
        "Initial schema"
        if rev["id"] == "0001"
        else (rev.get("summary") or ["No schema changes"])[0]
    )
    header = [comment(title[:1].upper() + title[1:]), ""]
    header += [f"- {comment(line)}" for line in rev.get("summary") or []] or [
        "- (no schema changes)"
    ]
    if rev.get("destructive"):
        header += [
            "",
            "Permanently changes existing data (confirmed when it was generated):",
        ]
        header += [f"- {comment(line)}" for line in rev["destructive"]]
    header += [
        "",
        f"Migration {rev['id']}"
        + (f" (after {down_id})" if down_id else "")
        + f", created {comment(rev.get('created_at') or '')}.",
        "Written by VengaiCode from this project's Architecture tables. `php artisan migrate`",
        "applies it (`php artisan migrate:rollback` undoes the newest). VengaiCode never",
        "rewrites a migration once generated, so it is safe to edit this file by hand.",
    ]
    up = migrations_sqlite.steps(previous_snapshot, snap) or ["-- (no schema changes)"]
    down = migrations_sqlite.steps(snap, previous_snapshot) or [
        "-- (no schema changes)"
    ]
    lines = [
        "<?php",
        "",
        *[f"// {line}".rstrip() for line in header],
        "",
        "use Illuminate\\Database\\Migrations\\Migration;",
        "use Illuminate\\Support\\Facades\\DB;",
        "use Illuminate\\Support\\Facades\\Schema;",
        "",
        "return new class extends Migration",
        "{",
        "    // SQLite changes a column by rebuilding its table, and with foreign keys on,",
        "    // dropping the old table deletes the rows that point at it. Foreign keys can",
        "    // only be switched off outside a transaction, so this migration opens its own",
        "    // one inside the switch instead of running in Laravel's usual one.",
        "    public $withinTransaction = false;",
        "",
        "    public function up(): void",
        "    {",
        *_nowdoc(up),
        "    }",
        "",
        "    public function down(): void",
        "    {",
        *_nowdoc(down),
        "    }",
        "",
        "    // The table definitions are SQL because Laravel's schema builder has no CHECK",
        "    // constraint, and SQLite only takes one when a table is created.",
        "    private function runStatements(string $sql): void",
        "    {",
        "        Schema::disableForeignKeyConstraints();",
        "        try {",
        "            DB::transaction(fn () => DB::unprepared($sql));",
        "        } finally {",
        "            Schema::enableForeignKeyConstraints();",
        "        }",
        "    }",
        "};",
    ]
    return "\n".join(lines) + "\n"
