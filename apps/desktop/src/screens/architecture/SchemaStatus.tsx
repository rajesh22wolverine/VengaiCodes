// ─── Schema status banners for the Architecture screen ───
//
// Two kinds of news about the database schema, kept visually distinct:
//   - notes:  what the backend dropped from (or added to) the AI's
//             proposal because it didn't validate — informational, the
//             saved schema is already consistent.
//   - issues: problems in the schema as it stands. These block the
//             "No AI" deterministic code generator (it refuses to build
//             from a schema it can't resolve), so they're a warning.

import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Info, Pencil } from "lucide-react";
import { SchemaIssue } from "./schemaTypes";
import { groupIssuesByTable } from "./schemaDraft";

export function SchemaNotesBanner({ notes }: { notes: string[] }) {
  const [open, setOpen] = useState(false);
  if (notes.length === 0) return null;

  const dropped = notes.filter((n) => n.startsWith("Dropped")).length;
  const other = notes.length - dropped;
  const title =
    dropped > 0
      ? `Baby Tiger dropped ${dropped} suggestion${dropped === 1 ? "" : "s"} that didn't validate` +
        (other > 0 ? ` and made ${other} other fix${other === 1 ? "" : "es"}` : "")
      : `Baby Tiger adjusted ${notes.length} of its suggestion${notes.length === 1 ? "" : "s"} so they validate`;

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-info-light)] px-4 py-3">
      <button onClick={() => setOpen((v) => !v)} className="w-full flex items-start gap-2 text-left">
        <Info className="w-3.5 h-3.5 text-[var(--color-info)] flex-shrink-0 mt-0.5" />
        <span className="flex-1 text-xs font-medium text-[var(--color-text-primary)] leading-relaxed">
          {title}
        </span>
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-[var(--color-text-tertiary)] flex-shrink-0 mt-0.5" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-[var(--color-text-tertiary)] flex-shrink-0 mt-0.5" />
        )}
      </button>
      {open && (
        <ul className="mt-2 ml-5 space-y-1 list-disc">
          {notes.map((note, i) => (
            <li key={i} className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
              {note}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Every issue, grouped under the table it belongs to. */
export function SchemaIssuesPanel({
  issues,
  title,
  onEdit,
}: {
  issues: SchemaIssue[];
  title: string;
  onEdit?: () => void;
}) {
  if (issues.length === 0) return null;
  const groups = groupIssuesByTable(issues);

  return (
    <div className="rounded-xl border border-[var(--color-warning)] bg-[var(--color-warning-light)] px-4 py-3">
      <div className="flex items-start gap-2">
        <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-warning)] flex-shrink-0 mt-0.5" />
        <p className="flex-1 text-xs font-semibold text-[var(--color-text-primary)] leading-relaxed">{title}</p>
        {onEdit && (
          <button
            onClick={onEdit}
            className="flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium text-[var(--color-text-secondary)] hover:text-[var(--color-primary)] hover:bg-[var(--color-surface)] transition-colors flex-shrink-0"
          >
            <Pencil className="w-3 h-3" /> Fix
          </button>
        )}
      </div>
      <div className="mt-2 ml-5 space-y-2">
        {groups.map(([table, list]) => (
          <div key={table || "__general__"}>
            <p className="text-xs font-semibold font-mono text-[var(--color-text-primary)]">
              {table || "General"}
            </p>
            <ul className="mt-0.5 space-y-0.5 list-disc ml-4">
              {list.map((issue, i) => (
                <li key={i} className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
                  {issue.message}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Small inline list of messages under an editor row. */
export function InlineIssues({ messages }: { messages: string[] }) {
  if (messages.length === 0) return null;
  return (
    <ul className="space-y-0.5">
      {messages.map((m, i) => (
        <li key={i} className="flex items-start gap-1.5 text-[11px] leading-snug text-[var(--color-error)]">
          <AlertTriangle className="w-3 h-3 flex-shrink-0 mt-px" />
          <span>{m}</span>
        </li>
      ))}
    </ul>
  );
}
