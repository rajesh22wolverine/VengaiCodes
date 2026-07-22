# ═══════════════════════════════════════════════════════════════
#  VengaiCode — Shared Rust Helpers
#  ai/codegen/backend/rust_common.py — NOT an adapter itself. A plain
#  serde/sqlx data struct doesn't care which web framework will use it,
#  so actix.py and axum.py share this one model-generation prompt
#  instead of duplicating it — their routes/wiring genuinely differ
#  (different web-framework APIs) and stay in their own files.
# ═══════════════════════════════════════════════════════════════

from app.ai.codegen.types import FileResult, ModelCtx
from app.ai.codegen_shared import GROQ_FILE_MAX_TOKENS, GeneratedFile, _pascal, _slug, generate_text_validated


async def generate_model(ctx: ModelCtx) -> FileResult:
    table_name = ctx.table.get("name", "Item")
    struct_name = _pascal(table_name)

    prompt = f"""You are Baby Tiger 🐯, VengaiCode's AI code generation assistant. Write ONE complete, real Rust struct for the "{table_name}" table of this app.

App: {ctx.project_name}
{ctx.requirements_text}
Table purpose: {ctx.table.get('purpose', '')}
Fields: {', '.join(ctx.table.get('key_fields', []))}

Requirements:
- Struct name: `pub struct {struct_name}`, with `pub id: i64` plus real `pub` fields (correct
  Rust types) matching the fields above — every field MUST be `pub`, since handler code in a
  different module constructs and reads these fields directly.
- Derive exactly: `#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, sqlx::FromRow)]`.
- Add a second `pub struct {struct_name}Input` (same derives minus `sqlx::FromRow`, same `pub`
  fields) with the same fields EXCEPT `id`, for use when creating/updating a record from a
  request body.
- Implement any validation logic implied by the key features / user stories above as a real
  method on {struct_name}Input (e.g. `pub fn validate(&self) -> Result<(), String>`), not a
  placeholder.
- No placeholders or TODOs — every field and method must be fully implemented.

Return ONLY the raw Rust code for this one file. No markdown fences, no explanation, no JSON."""

    content, issue = await generate_text_validated(prompt, "rust", GROQ_FILE_MAX_TOKENS)
    return GeneratedFile(
        path=f"backend/src/models/{_slug(table_name)}.rs",
        language="rust",
        content=content,
        description=f"Data struct for {table_name}",
    ), issue


def models_mod_rs(model_files: list[GeneratedFile]) -> str:
    lines = "\n".join(f"pub mod {f.path.split('/')[-1].removesuffix('.rs')};" for f in model_files)
    return lines + "\n" if lines else "// no models generated\n"


def _infer_sql_type(field_name: str) -> str:
    lowered = field_name.lower()
    if any(k in lowered for k in ("done", "active", "enabled", "completed", "is_", "has_")):
        return "BOOLEAN"
    if any(k in lowered for k in ("count", "quantity", "number", "age")):
        return "INTEGER"
    if any(k in lowered for k in ("price", "amount", "total", "cost")):
        return "REAL"
    return "TEXT"


def build_create_table_sql(table: dict) -> str:
    import re

    plural = f"{_slug(table.get('name', 'item'))}s"
    fields = [f for f in (table.get("key_fields", []) or []) if _slug(f) not in ("created_at", "updated_at")]
    columns = ",\n    ".join(f"{_slug(f)} {_infer_sql_type(f)}" for f in fields)
    columns_clause = f",\n    {columns}" if columns else ""
    return (
        f"CREATE TABLE IF NOT EXISTS {plural} (\n"
        f"    id INTEGER PRIMARY KEY AUTOINCREMENT{columns_clause}\n"
        f")"
    )


def view_name(method: str, path: str) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path.strip("/")).strip("_").lower() or "root"
    return f"{method.lower()}_{slug}"
