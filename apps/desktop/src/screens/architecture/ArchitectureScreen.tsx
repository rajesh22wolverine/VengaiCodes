import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft, Layers, Database, Webhook, Package,
  Loader2, ThumbsUp, BookOpen, GitBranch, Network, Copy, Check,
  Pencil, Plus, X, Save, XCircle
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient, { AI_REQUEST_TIMEOUT_MS } from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import ChatPanel from "@/components/chat/ChatPanel";

interface TechStack {
  frontend: string;
  backend: string;
  database: string;
  hosting: string;
}

interface DatabaseTable {
  name: string;
  purpose: string;
  key_fields: string[];
}

interface APIEndpoint {
  method: string;
  path: string;
  purpose: string;
}

interface ADR {
  title: string;
  decision: string;
  rationale: string;
  alternatives_considered: string[];
}

interface ArchitectureDesign {
  architecture_summary: string;
  tech_stack: TechStack;
  database_tables: DatabaseTable[];
  api_endpoints: APIEndpoint[];
  third_party_services: string[];
  adrs?: ADR[];
}

/** Mermaid source built deterministically by the backend from the
 * architecture above (no second AI call), so it can't contradict it. */
interface Blueprint {
  system_diagram?: string | null;
  erd?: string | null;
}

const METHOD_COLORS: Record<string, string> = {
  GET: "var(--color-success)",
  POST: "var(--color-primary)",
  PUT: "var(--color-warning)",
  PATCH: "var(--color-warning)",
  DELETE: "var(--color-error)",
};

const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

export default function ArchitectureScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [architecture, setArchitecture] = useState<ArchitectureDesign | null>(null);
  const [blueprint, setBlueprint] = useState<Blueprint>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  // Editing tables/endpoints directly — a separate local draft so Cancel
  // can discard changes without touching the saved architecture. Both the
  // AI and deterministic codegen paths read straight from these two
  // fields, so a saved edit is honored by the next generation with no
  // codegen-side changes.
  const [isEditing, setIsEditing] = useState(false);
  const [isSavingEdit, setIsSavingEdit] = useState(false);
  const [draftTables, setDraftTables] = useState<DatabaseTable[]>([]);
  const [draftEndpoints, setDraftEndpoints] = useState<APIEndpoint[]>([]);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/architecture/${projectId}`);
      setArchitecture(data.architecture);
      setBlueprint({ system_diagram: data.system_diagram, erd: data.erd });
      setIsLoading(false);
    } catch {
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/architecture/generate", {
        project_id: projectId,
      }, { timeout: AI_REQUEST_TIMEOUT_MS });
      setArchitecture(data.architecture);
      // The generate response carries the design itself; the deterministic
      // diagrams are built alongside it and come back on the GET.
      try {
        const { data: saved } = await apiClient.get(`/architecture/${projectId}`);
        setBlueprint({ system_diagram: saved.system_diagram, erd: saved.erd });
      } catch {
        setBlueprint({});
      }
      toast.success("Your architecture is ready! 🏗️🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to generate architecture.");
      navigate(`/project/${projectId}/uiux`);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownloadDocs = async () => {
    setIsDownloadingDocs(true);
    try {
      const response = await apiClient.get(`/export/${projectId}/documents`, {
        responseType: "blob",
      });
      const contentDisposition = response.headers["content-disposition"] || "";
      const filenameMatch = contentDisposition.match(/filename\s*=\s*"?([^";]+)"?/i);
      const downloadName = filenameMatch?.[1] || "documentation.zip";
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", downloadName);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Documentation bundle downloaded 🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to download documentation.");
    } finally {
      setIsDownloadingDocs(false);
    }
  };

  const handleApprove = async () => {
    setIsApproving(true);
    try {
      await apiClient.post("/architecture/approve", {
        project_id: projectId,
        approved: true,
      });
      toast.success("Architecture approved! Next: API Builder 🐯");
      navigate(`/project/${projectId}/codegen`);
    } catch (error: any) {
      toast.error(error.message || "Failed to approve.");
    } finally {
      setIsApproving(false);
    }
  };

  const startEditing = () => {
    if (!architecture) return;
    // Deep-copy so edits in the draft never mutate the saved architecture
    // until Save actually round-trips through the backend.
    setDraftTables(JSON.parse(JSON.stringify(architecture.database_tables)));
    setDraftEndpoints(JSON.parse(JSON.stringify(architecture.api_endpoints)));
    setIsEditing(true);
  };

  const cancelEditing = () => setIsEditing(false);

  const saveEdits = async () => {
    setIsSavingEdit(true);
    try {
      const { data } = await apiClient.put(`/architecture/${projectId}/edit`, {
        database_tables: draftTables,
        api_endpoints: draftEndpoints,
      });
      setArchitecture(data.architecture);
      setBlueprint({ system_diagram: data.system_diagram, erd: data.erd });
      setIsEditing(false);
      toast.success("Changes saved — review and approve again to continue 🐯");
    } catch (error: any) {
      toast.error(error.response?.data?.detail || error.message || "Failed to save changes.");
    } finally {
      setIsSavingEdit(false);
    }
  };

  const updateTable = (i: number, patch: Partial<DatabaseTable>) => {
    setDraftTables((prev) => prev.map((t, idx) => (idx === i ? { ...t, ...patch } : t)));
  };
  const addTable = () => setDraftTables((prev) => [...prev, { name: "", purpose: "", key_fields: [] }]);
  const removeTable = (i: number) => setDraftTables((prev) => prev.filter((_, idx) => idx !== i));
  const addField = (tableIndex: number, field: string) => {
    const trimmed = field.trim();
    if (!trimmed) return;
    setDraftTables((prev) =>
      prev.map((t, idx) => (idx === tableIndex ? { ...t, key_fields: [...t.key_fields, trimmed] } : t))
    );
  };
  const removeField = (tableIndex: number, fieldIndex: number) => {
    setDraftTables((prev) =>
      prev.map((t, idx) =>
        idx === tableIndex ? { ...t, key_fields: t.key_fields.filter((_, j) => j !== fieldIndex) } : t
      )
    );
  };

  const updateEndpoint = (i: number, patch: Partial<APIEndpoint>) => {
    setDraftEndpoints((prev) => prev.map((e, idx) => (idx === i ? { ...e, ...patch } : e)));
  };
  const addEndpoint = () => setDraftEndpoints((prev) => [...prev, { method: "GET", path: "/", purpose: "" }]);
  const removeEndpoint = (i: number) => setDraftEndpoints((prev) => prev.filter((_, idx) => idx !== i));

  if (isLoading || isGenerating) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 bg-[var(--color-background)]">
        <BabyTiger size={100} expression="thinking" />
        <p className="text-[var(--color-text-secondary)] text-sm">
          {isGenerating
            ? "Baby Tiger is planning your architecture... 🏗️🐯"
            : "Loading..."}
        </p>
      </div>
    );
  }

  if (!architecture) return null;

  const stackEntries = Object.entries(architecture.tech_stack) as [keyof TechStack, string][];

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--color-background)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <button
          onClick={() => navigate("/home")}
          className="p-2 rounded-lg hover:bg-[var(--color-surface-raised)] transition-colors"
        >
          <ArrowLeft className="w-4 h-4 text-[var(--color-text-secondary)]" />
        </button>
        <BabyTiger size={36} expression="happy" />
        <div className="flex-1">
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">
            Architecture
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Phase 3 of 7 — Review and approve to continue
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-6">

          {/* Summary */}
          <Section icon={Layers} title="Architecture Summary">
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {architecture.architecture_summary}
            </p>
          </Section>

          {/* Tech Stack */}
          <Section icon={Package} title="Tech Stack">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {stackEntries.map(([key, value]) => (
                <div
                  key={key}
                  className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
                >
                  <p className="text-xs font-semibold text-[var(--color-primary)] uppercase tracking-wider mb-1.5">
                    {key}
                  </p>
                  <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
                    {value}
                  </p>
                </div>
              ))}
            </div>
          </Section>

          {/* Database Tables */}
          <Section
            icon={Database}
            title={`Database Tables (${(isEditing ? draftTables : architecture.database_tables).length})`}
            action={!isEditing && <EditButton onClick={startEditing} />}
          >
            {isEditing ? (
              <div className="space-y-3">
                {draftTables.map((table, i) => (
                  <TableEditorCard
                    key={i}
                    table={table}
                    onChange={(patch) => updateTable(i, patch)}
                    onRemove={() => removeTable(i)}
                    onAddField={(f) => addField(i, f)}
                    onRemoveField={(j) => removeField(i, j)}
                  />
                ))}
                <button
                  onClick={addTable}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-dashed border-[var(--color-border)] text-xs font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)] transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" /> Add table
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {architecture.database_tables.map((table, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                    className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <Database className="w-3.5 h-3.5 text-[var(--color-primary)] flex-shrink-0" />
                      <h4 className="text-sm font-semibold text-[var(--color-text-primary)] font-mono">
                        {table.name}
                      </h4>
                    </div>
                    <p className="text-xs text-[var(--color-text-secondary)] mb-3 leading-relaxed">
                      {table.purpose}
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {table.key_fields.map((field, j) => (
                        <span
                          key={j}
                          className="px-2 py-1 rounded-md bg-[var(--color-surface)] text-[var(--color-text-tertiary)] text-xs font-mono border border-[var(--color-border)]"
                        >
                          {field}
                        </span>
                      ))}
                    </div>
                  </motion.div>
                ))}
              </div>
            )}
          </Section>

          {/* API Endpoints */}
          <Section
            icon={Webhook}
            title={`API Endpoints (${(isEditing ? draftEndpoints : architecture.api_endpoints).length})`}
            action={!isEditing && <EditButton onClick={startEditing} />}
          >
            {isEditing ? (
              <div className="space-y-2">
                {draftEndpoints.map((endpoint, i) => (
                  <div key={i} className="flex items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-2.5">
                    <select
                      value={endpoint.method}
                      onChange={(e) => updateEndpoint(i, { method: e.target.value })}
                      className="px-2 py-1.5 rounded-md text-xs font-bold font-mono bg-[var(--color-surface)] border border-[var(--color-border)] text-[var(--color-text-primary)] flex-shrink-0"
                    >
                      {HTTP_METHODS.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                    <input
                      value={endpoint.path}
                      onChange={(e) => updateEndpoint(i, { path: e.target.value })}
                      placeholder="/resource"
                      className="w-40 flex-shrink-0 px-2 py-1.5 rounded-md text-xs font-mono bg-[var(--color-surface)] border border-[var(--color-border)] text-[var(--color-text-primary)]"
                    />
                    <input
                      value={endpoint.purpose}
                      onChange={(e) => updateEndpoint(i, { purpose: e.target.value })}
                      placeholder="What this endpoint does"
                      className="flex-1 px-2 py-1.5 rounded-md text-xs bg-[var(--color-surface)] border border-[var(--color-border)] text-[var(--color-text-primary)]"
                    />
                    <button onClick={() => removeEndpoint(i)} className="p-1.5 rounded-md text-[var(--color-text-tertiary)] hover:text-[var(--color-error)] hover:bg-[var(--color-surface)] transition-colors flex-shrink-0">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
                <button
                  onClick={addEndpoint}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border border-dashed border-[var(--color-border)] text-xs font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)] transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" /> Add endpoint
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                {architecture.api_endpoints.map((endpoint, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3"
                  >
                    <span
                      className="px-2 py-1 rounded-md text-xs font-bold text-white flex-shrink-0 font-mono"
                      style={{
                        backgroundColor: METHOD_COLORS[endpoint.method.toUpperCase()] || "var(--color-text-tertiary)",
                      }}
                    >
                      {endpoint.method.toUpperCase()}
                    </span>
                    <code className="text-xs font-mono text-[var(--color-text-primary)] flex-shrink-0">
                      {endpoint.path}
                    </code>
                    <span className="text-xs text-[var(--color-text-tertiary)] truncate">
                      {endpoint.purpose}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {isEditing && (
            <div className="sticky bottom-0 flex items-center justify-between gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 shadow-lg">
              <p className="text-xs text-[var(--color-text-tertiary)] px-2">
                Saving will require re-approval before the next code generation.
              </p>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={cancelEditing}
                  disabled={isSavingEdit}
                  className="px-4 py-2 rounded-xl border border-[var(--color-border)] text-xs font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-surface-raised)] transition-colors disabled:opacity-60 flex items-center gap-1.5"
                >
                  <XCircle className="w-3.5 h-3.5" /> Cancel
                </button>
                <button
                  onClick={saveEdits}
                  disabled={isSavingEdit}
                  className="px-4 py-2 rounded-xl bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center gap-1.5"
                >
                  {isSavingEdit ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                  Save Changes
                </button>
              </div>
            </div>
          )}

          {/* Third-Party Services */}
          {architecture.third_party_services.length > 0 && (
            <Section icon={Package} title="Third-Party Services">
              <div className="flex flex-wrap gap-2">
                {architecture.third_party_services.map((service, i) => (
                  <span
                    key={i}
                    className="px-3 py-1.5 rounded-lg bg-[var(--color-primary-light)] text-[var(--color-primary)] text-xs font-medium"
                  >
                    {service}
                  </span>
                ))}
              </div>
              <p className="text-xs text-[var(--color-text-tertiary)] mt-3">
                Open-source and free options are chosen by default — a paid service only appears
                here if you said you already have your own account for it.
              </p>
            </Section>
          )}

          {/* Architecture Decision Records */}
          {architecture.adrs && architecture.adrs.length > 0 && (
            <Section icon={GitBranch} title={`Decision Records (${architecture.adrs.length})`}>
              <div className="space-y-3">
                {architecture.adrs.map((adr, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
                  >
                    <p className="text-sm font-semibold text-[var(--color-text-primary)] mb-2">{adr.title}</p>
                    <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed mb-2">
                      <span className="text-[var(--color-primary)] font-medium">Decision: </span>
                      {adr.decision}
                    </p>
                    <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
                      <span className="text-[var(--color-primary)] font-medium">Why: </span>
                      {adr.rationale}
                    </p>
                    {adr.alternatives_considered?.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-3">
                        <span className="text-xs text-[var(--color-text-tertiary)] mr-1">Also considered:</span>
                        {adr.alternatives_considered.map((alt, j) => (
                          <span
                            key={j}
                            className="px-2 py-0.5 rounded-md bg-[var(--color-bg)] border border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]"
                          >
                            {alt}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Blueprint diagrams */}
          {(blueprint.system_diagram || blueprint.erd) && (
            <Section icon={Network} title="Blueprint Diagrams">
              <p className="text-xs text-[var(--color-text-tertiary)] mb-3">
                Built directly from the architecture above — not a separate AI guess, so they can't
                disagree with it. This is Mermaid source: it renders as a diagram in GitHub, Notion,
                or mermaid.live.
              </p>
              <div className="space-y-3">
                {blueprint.system_diagram && (
                  <DiagramBlock label="System diagram" code={blueprint.system_diagram} />
                )}
                {blueprint.erd && <DiagramBlock label="Database ERD" code={blueprint.erd} />}
              </div>
            </Section>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="flex-shrink-0 px-6 py-4 border-t border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Review the architecture above. Once approved, Baby Tiger starts building 🚀
          </p>
          <div className="flex items-center gap-3 flex-shrink-0">
            <button
              onClick={handleDownloadDocs}
              disabled={isDownloadingDocs}
              className="px-4 py-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-primary)] font-medium text-sm hover:bg-[var(--color-surface-raised)] transition-colors disabled:opacity-60 flex items-center gap-2"
            >
              {isDownloadingDocs ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <BookOpen className="w-4 h-4" />
              )}
              Export Docs
            </button>
            <button
              onClick={handleApprove}
              disabled={isApproving}
              className="px-6 py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center gap-2"
            >
              {isApproving ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <ThumbsUp className="w-4 h-4" />
              )}
              Approve & Continue
            </button>
          </div>
        </div>
      </div>
      <ChatPanel projectId={projectId} phase="architecture" />
    </div>
  );
}

/** Shows Mermaid diagram source with a copy button. Deliberately not
 * rendered to SVG here: that would mean pulling in mermaid.js (~2MB) for
 * two small diagrams, and the source is directly usable as-is anywhere
 * Mermaid is supported. */
function DiagramBlock({ label, code }: { label: string; code: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Couldn't copy to the clipboard.");
    }
  };

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)]">
        <span className="text-xs font-semibold text-[var(--color-text-primary)]">{label}</span>
        <button
          onClick={copy}
          className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs text-[var(--color-text-tertiary)] hover:text-[var(--color-primary)] hover:bg-[var(--color-bg)] transition-colors"
        >
          {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="px-4 py-3 text-xs text-[var(--color-text-secondary)] overflow-x-auto font-mono leading-relaxed">
        {code}
      </pre>
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  action,
  children,
}: {
  icon: React.ElementType;
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
    >
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-[var(--color-primary)]" />
          <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
            {title}
          </h3>
        </div>
        {action}
      </div>
      {children}
    </motion.div>
  );
}

function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium text-[var(--color-text-tertiary)] hover:text-[var(--color-primary)] hover:bg-[var(--color-primary-light)] transition-colors"
    >
      <Pencil className="w-3 h-3" /> Edit
    </button>
  );
}

/** One editable table card: name, purpose, and a chip list of fields
 * with per-field remove + an inline "add field" input (Enter to add). */
function TableEditorCard({
  table,
  onChange,
  onRemove,
  onAddField,
  onRemoveField,
}: {
  table: DatabaseTable;
  onChange: (patch: Partial<DatabaseTable>) => void;
  onRemove: () => void;
  onAddField: (field: string) => void;
  onRemoveField: (fieldIndex: number) => void;
}) {
  const [newField, setNewField] = useState("");

  const commitField = () => {
    if (!newField.trim()) return;
    onAddField(newField);
    setNewField("");
  };

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4">
      <div className="flex items-start gap-2 mb-2">
        <input
          value={table.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="table_name"
          className="flex-1 px-2 py-1.5 rounded-md text-sm font-mono font-semibold bg-[var(--color-surface)] border border-[var(--color-border)] text-[var(--color-text-primary)]"
        />
        <button onClick={onRemove} className="p-1.5 rounded-md text-[var(--color-text-tertiary)] hover:text-[var(--color-error)] hover:bg-[var(--color-surface)] transition-colors flex-shrink-0">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      <input
        value={table.purpose}
        onChange={(e) => onChange({ purpose: e.target.value })}
        placeholder="What this table is for"
        className="w-full mb-3 px-2 py-1.5 rounded-md text-xs bg-[var(--color-surface)] border border-[var(--color-border)] text-[var(--color-text-secondary)]"
      />
      <div className="flex flex-wrap gap-1.5 mb-2">
        {table.key_fields.map((field, j) => (
          <span
            key={j}
            className="flex items-center gap-1 px-2 py-1 rounded-md bg-[var(--color-surface)] text-[var(--color-text-tertiary)] text-xs font-mono border border-[var(--color-border)]"
          >
            {field}
            <button onClick={() => onRemoveField(j)} className="hover:text-[var(--color-error)]">
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
      </div>
      <input
        value={newField}
        onChange={(e) => setNewField(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commitField();
          }
        }}
        onBlur={commitField}
        placeholder="+ add field, press Enter"
        className="w-full px-2 py-1 rounded-md text-xs font-mono bg-transparent border border-dashed border-[var(--color-border)] text-[var(--color-text-secondary)]"
      />
    </div>
  );
}
