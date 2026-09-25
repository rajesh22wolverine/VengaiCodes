import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft, Layers, Database, Webhook, Package,
  Loader2, ThumbsUp, BookOpen, GitBranch, Network, Copy, Check,
  Pencil, Plus, X, Save, XCircle, AlertTriangle, CheckCircle2, CloudOff
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient, { AI_REQUEST_TIMEOUT_MS } from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import ChatPanel from "@/components/chat/ChatPanel";
import {
  DatabaseTable,
  DraftTable,
  ResolvedTable,
  SchemaIssue,
  SchemaValidationResult,
} from "./schemaTypes";
import {
  draftToPayload,
  emptyDraftTable,
  issuesForTable,
  removeTable,
  renameField,
  renameTable,
  tableToDraft,
} from "./schemaDraft";
import SchemaTableEditor from "./SchemaTableEditor";
import SchemaTableView from "./SchemaTableView";
import { SchemaIssuesPanel, SchemaNotesBanner } from "./SchemaStatus";

interface TechStack {
  frontend: string;
  backend: string;
  database: string;
  hosting: string;
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

/** GET /architecture/{id} and PUT /architecture/{id}/edit. The schema_*
 *  and resolved_tables fields are absent on an older backend, in which
 *  case the screen shows tables exactly the way it used to. */
interface ArchitectureResponse {
  architecture: ArchitectureDesign;
  system_diagram?: string | null;
  erd?: string | null;
  /** Live validation of the saved tables — these block No-AI codegen. */
  schema_issues?: SchemaIssue[];
  /** What was dropped from the AI's proposal, and why. */
  schema_notes?: string[];
  resolved_tables?: ResolvedTable[];
}

/** A validate response plus the seed-row index map of the draft it was
 *  computed from (blank seed rows aren't sent, so positions shift). */
interface LiveValidation extends SchemaValidationResult {
  seedIndexMaps: number[][];
}

const METHOD_COLORS: Record<string, string> = {
  GET: "var(--color-success)",
  POST: "var(--color-primary)",
  PUT: "var(--color-warning)",
  PATCH: "var(--color-warning)",
  DELETE: "var(--color-error)",
};

const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

// Long enough that typing a word doesn't fire a request per keystroke,
// short enough that the problem list feels live.
const VALIDATE_DEBOUNCE_MS = 600;

/** FastAPI's `detail` is usually a string; a 422 carries a list. */
function detailToText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join("\n");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return "";
}

export default function ArchitectureScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [architecture, setArchitecture] = useState<ArchitectureDesign | null>(null);
  const [blueprint, setBlueprint] = useState<Blueprint>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  // The saved schema as the backend resolved it: real types/keys for the
  // read-only view, problems that block No-AI codegen, and notes about
  // what was dropped from the AI's proposal.
  const [schemaIssues, setSchemaIssues] = useState<SchemaIssue[]>([]);
  const [schemaNotes, setSchemaNotes] = useState<string[]>([]);
  const [resolvedTables, setResolvedTables] = useState<ResolvedTable[]>([]);

  // Editing tables/endpoints directly — a separate local draft so Cancel
  // can discard changes without touching the saved architecture. Both the
  // AI and deterministic codegen paths read straight from these two
  // fields, so a saved edit is honored by the next generation with no
  // codegen-side changes.
  const [isEditing, setIsEditing] = useState(false);
  const [isSavingEdit, setIsSavingEdit] = useState(false);
  const [draftTables, setDraftTables] = useState<DraftTable[]>([]);
  // Stable React keys for the table cards, so removing one table doesn't
  // hand its neighbours' open/closed sections to the wrong card.
  const [draftIds, setDraftIds] = useState<number[]>([]);
  const nextDraftId = useRef(0);
  const [draftEndpoints, setDraftEndpoints] = useState<APIEndpoint[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Renames are checked against the current draft synchronously (so a
  // clash can be refused before anything changes) — this always holds
  // the latest rendered draft.
  const draftRef = useRef<DraftTable[]>([]);
  draftRef.current = draftTables;

  // Live validation of the draft while editing (nothing is saved by it).
  const [liveValidation, setLiveValidation] = useState<LiveValidation | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [validationUnavailable, setValidationUnavailable] = useState(false);
  const validationSeq = useRef(0);
  const liveIssuesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadOrGenerate();
    // Once per project: loadOrGenerate is a new function every render, so
    // listing it would re-run the load (or an AI generation) on each one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    if (!isEditing) return;
    const seq = ++validationSeq.current;
    const timer = window.setTimeout(async () => {
      const { tables, seedIndexMaps } = draftToPayload(draftTables);
      setIsValidating(true);
      try {
        const { data } = await apiClient.post<SchemaValidationResult>(
          `/architecture/${projectId}/validate`,
          { database_tables: tables, api_endpoints: draftEndpoints }
        );
        if (seq !== validationSeq.current) return;
        setLiveValidation({ ...data, issues: data.issues ?? [], seedIndexMaps });
        setValidationUnavailable(false);
      } catch {
        // Live checking is a convenience: without it, Save still
        // validates on the server and lists every problem.
        if (seq === validationSeq.current) setValidationUnavailable(true);
      } finally {
        if (seq === validationSeq.current) setIsValidating(false);
      }
    }, VALIDATE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [isEditing, draftTables, draftEndpoints, projectId]);

  const applySchemaState = (data: Partial<ArchitectureResponse>) => {
    setSchemaIssues(data.schema_issues ?? []);
    setSchemaNotes(data.schema_notes ?? []);
    setResolvedTables(data.resolved_tables ?? []);
  };

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get<ArchitectureResponse>(`/architecture/${projectId}`);
      setArchitecture(data.architecture);
      setBlueprint({ system_diagram: data.system_diagram, erd: data.erd });
      applySchemaState(data);
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
      // diagrams and the resolved schema are built alongside it and come
      // back on the GET.
      try {
        const { data: saved } = await apiClient.get<ArchitectureResponse>(`/architecture/${projectId}`);
        setArchitecture(saved.architecture ?? data.architecture);
        setBlueprint({ system_diagram: saved.system_diagram, erd: saved.erd });
        applySchemaState(saved);
      } catch {
        setBlueprint({});
        applySchemaState({});
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

  const resolvedFor = (tables: ResolvedTable[] | undefined, name: string) =>
    (tables ?? []).find((r) => r.name.trim() === name.trim());

  const resetLiveValidation = () => {
    validationSeq.current += 1; // anything still in flight is now stale
    setLiveValidation(null);
    setIsValidating(false);
    setValidationUnavailable(false);
  };

  const startEditing = () => {
    if (!architecture) return;
    // tableToDraft copies everything, so edits in the draft never mutate
    // the saved architecture until Save round-trips through the backend.
    const tables = architecture.database_tables.map((t) => tableToDraft(t, resolvedFor(resolvedTables, t.name)));
    setDraftTables(tables);
    setDraftIds(tables.map(() => nextDraftId.current++));
    setDraftEndpoints(JSON.parse(JSON.stringify(architecture.api_endpoints)));
    resetLiveValidation();
    setSaveError(null);
    setIsEditing(true);
  };

  const cancelEditing = () => {
    resetLiveValidation();
    setSaveError(null);
    setIsEditing(false);
  };

  const saveEdits = async () => {
    setIsSavingEdit(true);
    setSaveError(null);
    try {
      const { tables } = draftToPayload(draftRef.current);
      // A 400 is an expected answer here (the full list of problems), so
      // it's taken as a response rather than thrown — the shared axios
      // interceptor would otherwise flatten it into a one-line toast.
      const response = await apiClient.put(
        `/architecture/${projectId}/edit`,
        { database_tables: tables, api_endpoints: draftEndpoints },
        { validateStatus: (s) => (s >= 200 && s < 300) || s === 400 }
      );
      if (response.status === 400) {
        setSaveError(detailToText(response.data?.detail) || "The changes couldn't be saved.");
        return;
      }
      const data = response.data as ArchitectureResponse;
      setArchitecture(data.architecture);
      setBlueprint({ system_diagram: data.system_diagram, erd: data.erd });
      applySchemaState(data);
      resetLiveValidation();
      setIsEditing(false);
      toast.success("Changes saved — review and approve again to continue 🐯");
    } catch (error: any) {
      setSaveError(error.message || "Failed to save changes.");
    } finally {
      setIsSavingEdit(false);
    }
  };

  const updateDraftTable = (i: number, fn: (t: DraftTable) => DraftTable) => {
    setDraftTables((prev) => prev.map((t, idx) => (idx === i ? fn(t) : t)));
  };
  const addTable = () => {
    setDraftTables((prev) => [...prev, emptyDraftTable()]);
    setDraftIds((prev) => [...prev, nextDraftId.current++]);
  };
  const removeDraftTable = (i: number) => {
    setDraftTables((prev) => removeTable(prev, i));
    setDraftIds((prev) => prev.filter((_, idx) => idx !== i));
  };
  // Checked against the latest draft first so a clash is refused (and the
  // input reverted) before anything changes; then applied functionally.
  const commitTableRename = (i: number, name: string): boolean => {
    const check = renameTable(draftRef.current, i, name);
    if (!check.ok) {
      toast.error(check.error);
      return false;
    }
    setDraftTables((prev) => {
      const r = renameTable(prev, i, name);
      return r.ok ? r.value : prev;
    });
    return true;
  };
  const commitFieldRename = (ti: number, fi: number, name: string): boolean => {
    const check = renameField(draftRef.current, ti, fi, name);
    if (!check.ok) {
      toast.error(check.error);
      return false;
    }
    setDraftTables((prev) => {
      const r = renameField(prev, ti, fi, name);
      return r.ok ? r.value : prev;
    });
    return true;
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
  const liveIssues = liveValidation?.issues ?? [];
  const previewErd = isEditing && liveValidation?.erd ? liveValidation.erd : null;
  const erdToShow = previewErd ?? blueprint.erd;

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
        {/* The typed table editor needs the extra width for its field grid. */}
        <div className={`${isEditing ? "max-w-5xl" : "max-w-3xl"} mx-auto space-y-6`}>

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
                <p className="text-xs text-[var(--color-text-tertiary)] leading-relaxed">
                  Leave a field's type on Auto to keep inferring it from the name, or pick one to pin it.
                  Changes are checked as you type; the same checks run again when you save.
                </p>
                <div ref={liveIssuesRef}>
                  <SchemaIssuesPanel
                    issues={liveIssues}
                    title={`${liveIssues.length} problem${liveIssues.length === 1 ? "" : "s"} to fix before this can be saved`}
                  />
                </div>
                {draftTables.map((table, i) => (
                  <SchemaTableEditor
                    key={draftIds[i] ?? `t${i}`}
                    tables={draftTables}
                    tableIndex={i}
                    resolved={resolvedFor(liveValidation?.resolved_tables, table.name)}
                    issues={issuesForTable(liveIssues, table.name)}
                    seedIndexMap={liveValidation?.seedIndexMaps[i]}
                    onUpdate={(fn) => updateDraftTable(i, fn)}
                    onRenameTable={(name) => commitTableRename(i, name)}
                    onRenameField={(fi, name) => commitFieldRename(i, fi, name)}
                    onRemove={() => removeDraftTable(i)}
                    onError={(message) => toast.error(message)}
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
              <div className="space-y-3">
                <SchemaNotesBanner notes={schemaNotes} />
                <SchemaIssuesPanel
                  issues={schemaIssues}
                  title={`${schemaIssues.length} schema problem${schemaIssues.length === 1 ? "" : "s"} — No-AI code generation is blocked until ${schemaIssues.length === 1 ? "it's" : "they're"} fixed`}
                  onEdit={startEditing}
                />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {architecture.database_tables.map((table, i) => (
                    <SchemaTableView
                      key={i}
                      table={table}
                      resolved={resolvedFor(resolvedTables, table.name)}
                      issueCount={issuesForTable(schemaIssues, table.name).length}
                      delay={i * 0.05}
                    />
                  ))}
                </div>
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
            <div className="sticky bottom-0 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-3 shadow-lg space-y-2">
              {saveError && (
                <div className="flex items-start gap-2 rounded-lg border border-[var(--color-error)] bg-[var(--color-error-light)] px-3 py-2">
                  <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-error)] flex-shrink-0 mt-0.5" />
                  <p className="flex-1 max-h-40 overflow-y-auto text-xs text-[var(--color-text-primary)] leading-relaxed whitespace-pre-line">
                    {saveError}
                  </p>
                  <button
                    onClick={() => setSaveError(null)}
                    title="Dismiss"
                    className="p-0.5 rounded text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)] flex-shrink-0"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
              <div className="flex items-center justify-between gap-3">
                <div className="px-2 min-w-0">
                  <LiveValidationStatus
                    isValidating={isValidating}
                    unavailable={validationUnavailable}
                    result={liveValidation}
                    onShowIssues={() => liveIssuesRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })}
                  />
                  <p className="text-xs text-[var(--color-text-tertiary)]">
                    Saving will require re-approval before the next code generation.
                  </p>
                </div>
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
                            className="px-2 py-0.5 rounded-md bg-[var(--color-background)] border border-[var(--color-border)] text-xs text-[var(--color-text-tertiary)]"
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
          {(blueprint.system_diagram || erdToShow) && (
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
                {erdToShow && (
                  <DiagramBlock
                    label={previewErd ? "Database ERD — preview of your unsaved edits" : "Database ERD"}
                    code={erdToShow}
                  />
                )}
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

/** One-line state of the live check, shown in the sticky save bar. */
function LiveValidationStatus({
  isValidating,
  unavailable,
  result,
  onShowIssues,
}: {
  isValidating: boolean;
  unavailable: boolean;
  result: LiveValidation | null;
  onShowIssues: () => void;
}) {
  if (isValidating || (!result && !unavailable)) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-[var(--color-text-tertiary)]">
        <Loader2 className="w-3 h-3 animate-spin" /> Checking the schema…
      </p>
    );
  }
  if (unavailable) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-[var(--color-text-tertiary)]">
        <CloudOff className="w-3 h-3" /> Live checking is unavailable — Save will still check everything.
      </p>
    );
  }
  const count = result?.issues.length ?? 0;
  if (count === 0) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-[var(--color-success)]">
        <CheckCircle2 className="w-3 h-3" /> Schema checks out.
      </p>
    );
  }
  return (
    <button
      onClick={onShowIssues}
      className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-warning)] hover:underline"
    >
      <AlertTriangle className="w-3 h-3" /> {count} problem{count === 1 ? "" : "s"} — show
    </button>
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
          className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs text-[var(--color-text-tertiary)] hover:text-[var(--color-primary)] hover:bg-[var(--color-background)] transition-colors"
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
