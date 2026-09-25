import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Keyboard,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import {
  AlertTriangle, BookOpen, Database, GitBranch, Layers, Network, Package, Pencil, Plus,
  Save, ScanSearch, ThumbsUp, Webhook, X, XCircle,
} from "lucide-react-native";

import apiClient from "@/lib/api";
import { downloadAndShareFile } from "@/lib/download";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import PhaseHeader from "@/components/phase/PhaseHeader";
import PhaseLoading from "@/components/phase/PhaseLoading";
import PhaseFooter from "@/components/phase/PhaseFooter";
import Section from "@/components/ui/Section";
import {
  DatabaseTable,
  DraftTable,
  ResolvedTable,
  SchemaIssue,
  SchemaValidationResult,
} from "@/lib/schemaTypes";
import {
  draftToPayload,
  emptyDraftTable,
  issuesForTable,
  removeTable,
  renameField,
  renameTable,
  tableToDraft,
} from "@/lib/schemaDraft";
import { detailToText, plural } from "@/lib/schemaEditorView";
import SchemaTableEditor from "@/components/architecture/SchemaTableEditor";
import SchemaTableView from "@/components/architecture/SchemaTableView";
import {
  LiveValidationStatus,
  SchemaIssuesPanel,
  SchemaNotesBanner,
} from "@/components/architecture/SchemaStatus";
import { PendingEditsContext, usePendingEdits } from "@/components/architecture/CommitTextInput";

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

/** Mermaid source the backend builds deterministically from the
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
  GET: "#22c55e",
  POST: "#f97316",
  PUT: "#eab308",
  PATCH: "#eab308",
  DELETE: "#ef4444",
};

const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

// Long enough that typing a word doesn't fire a request per keystroke on
// a phone connection, short enough that the problem list feels live.
const VALIDATE_DEBOUNCE_MS = 800;

const resolvedFor = (tables: ResolvedTable[] | undefined, name: string) =>
  (tables ?? []).find((r) => r.name.trim() === name.trim());

export default function ArchitectureScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [architecture, setArchitecture] = useState<ArchitectureDesign | null>(null);
  const [blueprint, setBlueprint] = useState<Blueprint>({});
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  // The saved schema as the backend resolved it: real types/keys for the
  // read-only cards, problems that block No-AI codegen, and notes about
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
  // hand its neighbours' open/closed rows to the wrong card.
  const [draftIds, setDraftIds] = useState<number[]>([]);
  const nextDraftId = useRef(0);
  const [draftEndpoints, setDraftEndpoints] = useState<APIEndpoint[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);

  // The draft's source of truth. Every edit is applied to these refs
  // synchronously (then mirrored into state to re-render), so a rename
  // can be checked against the latest draft and refused before anything
  // changes, and a save that first flushes an in-progress rename reads
  // the draft WITH that rename — no waiting for a re-render.
  const draftRef = useRef<DraftTable[]>([]);
  const endpointsRef = useRef<APIEndpoint[]>([]);
  const { registry: pendingEdits, flushAll: flushPendingEdits } = usePendingEdits();

  // Live validation of the draft while editing (nothing is saved by it).
  const [liveValidation, setLiveValidation] = useState<LiveValidation | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [validationUnavailable, setValidationUnavailable] = useState(false);
  const validationSeq = useRef(0);
  const lastValidated = useRef<{ tables: DraftTable[]; endpoints: APIEndpoint[] } | null>(null);

  const scrollRef = useRef<ScrollView>(null);
  const tablesSectionY = useRef(0);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const applyDraft = useCallback((fn: (prev: DraftTable[]) => DraftTable[]) => {
    const next = fn(draftRef.current);
    if (next === draftRef.current) return;
    draftRef.current = next;
    setDraftTables(next);
  }, []);

  const applyEndpoints = (fn: (prev: APIEndpoint[]) => APIEndpoint[]) => {
    const next = fn(endpointsRef.current);
    endpointsRef.current = next;
    setDraftEndpoints(next);
  };

  const runValidation = useCallback(async () => {
    const tablesNow = draftRef.current;
    const endpointsNow = endpointsRef.current;
    lastValidated.current = { tables: tablesNow, endpoints: endpointsNow };
    const seq = ++validationSeq.current;
    const { tables, seedIndexMaps } = draftToPayload(tablesNow);
    setIsValidating(true);
    try {
      const { data } = await apiClient.post<SchemaValidationResult>(`/architecture/${projectId}/validate`, {
        database_tables: tables,
        api_endpoints: endpointsNow,
      });
      if (seq !== validationSeq.current) return;
      setLiveValidation({ ...data, issues: data.issues ?? [], seedIndexMaps });
      setValidationUnavailable(false);
    } catch {
      // Live checking is a convenience: without it, Save still validates
      // on the server and lists every problem.
      if (seq === validationSeq.current) setValidationUnavailable(true);
    } finally {
      if (seq === validationSeq.current) setIsValidating(false);
    }
  }, [projectId]);

  // Re-check the draft ~800ms after the last change. Skipped when this
  // exact draft was just checked (e.g. by the Check schema button).
  useEffect(() => {
    if (!isEditing) return;
    const last = lastValidated.current;
    if (last && last.tables === draftTables && last.endpoints === draftEndpoints) return;
    validationSeq.current += 1; // an answer for an older draft is now stale
    const timer = setTimeout(() => {
      void runValidation();
    }, VALIDATE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [isEditing, draftTables, draftEndpoints, runValidation]);

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
      const { data } = await apiClient.post("/architecture/generate", { project_id: projectId });
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
      showToast("Your architecture is ready! 🏗️🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to generate architecture.", "error");
      router.replace(`/(app)/project/${projectId}/uiux` as any);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownloadDocs = async () => {
    setIsDownloadingDocs(true);
    try {
      await downloadAndShareFile(`/export/${projectId}/documents`, "documentation.zip");
      showToast("Documentation bundle downloaded 🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to download documentation.", "error");
    } finally {
      setIsDownloadingDocs(false);
    }
  };

  const handleApprove = async () => {
    setIsApproving(true);
    try {
      await apiClient.post("/architecture/approve", { project_id: projectId, approved: true });
      showToast("Architecture approved! Next: API Builder 🐯");
      router.replace(`/(app)/project/${projectId}/codegen` as any);
    } catch (error: any) {
      showToast(error.message || "Failed to approve.", "error");
    } finally {
      setIsApproving(false);
    }
  };

  const resetLiveValidation = () => {
    validationSeq.current += 1; // anything still in flight is now stale
    lastValidated.current = null;
    setLiveValidation(null);
    setIsValidating(false);
    setValidationUnavailable(false);
  };

  const startEditing = () => {
    if (!architecture) return;
    // tableToDraft copies everything, so edits in the draft never mutate
    // the saved architecture until Save round-trips through the backend.
    const tables = architecture.database_tables.map((t) => tableToDraft(t, resolvedFor(resolvedTables, t.name)));
    draftRef.current = tables;
    setDraftTables(tables);
    setDraftIds(tables.map(() => nextDraftId.current++));
    const endpoints: APIEndpoint[] = JSON.parse(JSON.stringify(architecture.api_endpoints));
    endpointsRef.current = endpoints;
    setDraftEndpoints(endpoints);
    resetLiveValidation();
    setSaveError(null);
    setIsEditing(true);
  };

  const cancelEditing = () => {
    Keyboard.dismiss();
    resetLiveValidation();
    setSaveError(null);
    setIsEditing(false);
  };

  const saveEdits = async () => {
    // A name still being typed is part of what the user means to save.
    if (!flushPendingEdits()) return;
    Keyboard.dismiss();
    setIsSavingEdit(true);
    setSaveError(null);
    try {
      const { tables } = draftToPayload(draftRef.current);
      // A 400 is an expected answer here (the full list of problems), so
      // it's taken as a response rather than thrown — the shared axios
      // interceptor would otherwise flatten it into a one-line toast.
      const response = await apiClient.put(
        `/architecture/${projectId}/edit`,
        { database_tables: tables, api_endpoints: endpointsRef.current },
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
      showToast("Changes saved — review and approve again to continue 🐯");
    } catch (error: any) {
      setSaveError(error.message || "Failed to save changes.");
    } finally {
      setIsSavingEdit(false);
    }
  };

  const checkSchemaNow = () => {
    if (!flushPendingEdits()) return;
    Keyboard.dismiss();
    void runValidation();
  };

  const showLiveIssues = () => {
    scrollRef.current?.scrollTo({ y: Math.max(0, tablesSectionY.current - 8), animated: true });
  };

  const updateDraftTable = (i: number, fn: (t: DraftTable) => DraftTable) => {
    applyDraft((prev) => {
      const current = prev[i];
      if (!current) return prev;
      const next = fn(current);
      if (next === current) return prev;
      const copy = [...prev];
      copy[i] = next;
      return copy;
    });
  };
  const addTable = () => {
    const id = nextDraftId.current++;
    applyDraft((prev) => [...prev, emptyDraftTable()]);
    setDraftIds((prev) => [...prev, id]);
  };
  const removeDraftTable = (i: number) => {
    const table = draftRef.current[i];
    if (!table) return;
    const remove = () => {
      applyDraft((prev) => removeTable(prev, i));
      setDraftIds((prev) => prev.filter((_, idx) => idx !== i));
    };
    // One stray tap on a small × shouldn't take a whole table with it.
    if (!table.name.trim() && table.key_fields.length === 0) {
      remove();
      return;
    }
    Alert.alert(
      `Remove ${table.name.trim() ? `"${table.name.trim()}"` : "this table"}?`,
      "Its fields, checks, indexes and seed rows go with it, and links to it from other tables become plain " +
        "fields. Nothing is saved until you tap Save Changes.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Remove", style: "destructive", onPress: remove },
      ]
    );
  };
  // Checked against the latest draft first so a clash is refused (and the
  // input reverted) before anything changes. `expected` guards against a
  // commit arriving after the table/field it was typed into has moved.
  const commitTableRename = (i: number, expected: string, name: string): boolean => {
    if (draftRef.current[i]?.name !== expected) return false;
    const result = renameTable(draftRef.current, i, name);
    if (!result.ok) {
      showToast(result.error, "error");
      return false;
    }
    applyDraft(() => result.value);
    return true;
  };
  const commitFieldRename = (ti: number, fi: number, expected: string, name: string): boolean => {
    if (draftRef.current[ti]?.key_fields[fi] !== expected) return false;
    const result = renameField(draftRef.current, ti, fi, name);
    if (!result.ok) {
      showToast(result.error, "error");
      return false;
    }
    applyDraft(() => result.value);
    return true;
  };

  const updateEndpoint = (i: number, patch: Partial<APIEndpoint>) => {
    applyEndpoints((prev) => prev.map((e, idx) => (idx === i ? { ...e, ...patch } : e)));
  };
  const addEndpoint = () => applyEndpoints((prev) => [...prev, { method: "GET", path: "/", purpose: "" }]);
  const removeEndpoint = (i: number) => applyEndpoints((prev) => prev.filter((_, idx) => idx !== i));

  if (isLoading || isGenerating) {
    return <PhaseLoading message={isGenerating ? "Baby Tiger is planning your architecture... 🏗️🐯" : "Loading..."} />;
  }

  if (!architecture) return null;

  const stackEntries = Object.entries(architecture.tech_stack) as [keyof TechStack, string][];
  const liveIssues = liveValidation?.issues ?? [];
  const liveCheck = {
    isValidating,
    unavailable: validationUnavailable,
    issueCount: liveValidation ? liveIssues.length : null,
  };
  const previewErd = isEditing && liveValidation?.erd ? liveValidation.erd : null;
  const erdToShow = previewErd ?? blueprint.erd;

  return (
    <KeyboardAvoidingView
      style={[styles.screen, { backgroundColor: colors.background }]}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <PhaseHeader title="Architecture" subtitle="Phase 3 of 7 — Review and approve to continue" />

      <PendingEditsContext.Provider value={pendingEdits}>
        <ScrollView
          ref={scrollRef}
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode="on-drag"
        >
          <Section icon={Layers} title="Architecture Summary">
            <Text style={[styles.body, { color: colors.textSecondary }]}>{architecture.architecture_summary}</Text>
          </Section>

          <Section icon={Package} title="Tech Stack">
            {stackEntries.map(([key, value]) => (
              <View key={key} style={[styles.stackCard, { backgroundColor: colors.background, borderColor: colors.border }]}>
                <Text style={{ color: colors.primary, fontSize: 10, fontWeight: "700", textTransform: "uppercase", marginBottom: 4 }}>
                  {key}
                </Text>
                <Text style={[styles.body, { color: colors.textSecondary }]}>{value}</Text>
              </View>
            ))}
          </Section>

          <View onLayout={(e) => (tablesSectionY.current = e.nativeEvent.layout.y)}>
            <Section
              icon={Database}
              title={`Database Tables (${(isEditing ? draftTables : architecture.database_tables).length})`}
              action={!isEditing && <EditButton onPress={startEditing} />}
            >
              {isEditing ? (
                <>
                  <Text style={[styles.help, { color: colors.textTertiary }]}>
                    Tap a field to set its type, keys, default and links. Leave the type on Auto to keep
                    inferring it from the name. Changes are checked as you go; Save checks everything again.
                  </Text>
                  <View style={[styles.checkRow, { borderColor: colors.border }]}>
                    <LiveValidationStatus state={liveCheck} />
                    <Pressable
                      onPress={checkSchemaNow}
                      disabled={isValidating}
                      style={[styles.checkButton, { borderColor: colors.primary }, isValidating && { opacity: 0.6 }]}
                      accessibilityRole="button"
                    >
                      <ScanSearch size={13} color={colors.primary} />
                      <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "700" }}>Check schema</Text>
                    </Pressable>
                  </View>
                  <SchemaIssuesPanel
                    issues={liveIssues}
                    title={`${plural(liveIssues.length, "problem")} to fix before this can be saved`}
                  />
                  {draftTables.map((table, i) => (
                    <SchemaTableEditor
                      key={draftIds[i] ?? `t${i}`}
                      tables={draftTables}
                      tableIndex={i}
                      resolved={resolvedFor(liveValidation?.resolved_tables, table.name)}
                      issues={issuesForTable(liveIssues, table.name)}
                      seedIndexMap={liveValidation?.seedIndexMaps[i]}
                      onUpdate={(fn) => updateDraftTable(i, fn)}
                      onRenameTable={(expected, name) => commitTableRename(i, expected, name)}
                      onRenameField={(fi, expected, name) => commitFieldRename(i, fi, expected, name)}
                      onRemove={() => removeDraftTable(i)}
                      onError={(message) => showToast(message, "error")}
                    />
                  ))}
                  <Pressable onPress={addTable} style={[styles.addRow, { borderColor: colors.border }]}>
                    <Plus size={14} color={colors.textSecondary} />
                    <Text style={{ color: colors.textSecondary, fontSize: 12, fontWeight: "600" }}>Add table</Text>
                  </Pressable>
                </>
              ) : (
                <>
                  <SchemaNotesBanner notes={schemaNotes} />
                  <SchemaIssuesPanel
                    issues={schemaIssues}
                    title={`${plural(schemaIssues.length, "schema problem")} — No-AI code generation is blocked until ${
                      schemaIssues.length === 1 ? "it's" : "they're"
                    } fixed`}
                    onEdit={startEditing}
                  />
                  {architecture.database_tables.map((table, i) => (
                    <SchemaTableView
                      key={i}
                      table={table}
                      resolved={resolvedFor(resolvedTables, table.name)}
                      issueCount={issuesForTable(schemaIssues, table.name).length}
                    />
                  ))}
                </>
              )}
            </Section>
          </View>

          <Section
            icon={Webhook}
            title={`API Endpoints (${(isEditing ? draftEndpoints : architecture.api_endpoints).length})`}
            action={!isEditing && <EditButton onPress={startEditing} />}
          >
            {isEditing ? (
              <>
                {draftEndpoints.map((endpoint, i) => (
                  <View key={i} style={[styles.editEndpointRow, { borderColor: colors.border, backgroundColor: colors.background }]}>
                    <View style={styles.methodChipRow}>
                      {HTTP_METHODS.map((m) => {
                        const active = endpoint.method === m;
                        return (
                          <Pressable
                            key={m}
                            onPress={() => updateEndpoint(i, { method: m })}
                            style={[
                              styles.methodChip,
                              { borderColor: colors.border },
                              active && { backgroundColor: colors.primary, borderColor: colors.primary },
                            ]}
                          >
                            <Text style={{ fontSize: 10, fontWeight: "700", color: active ? "#fff" : colors.textSecondary }}>{m}</Text>
                          </Pressable>
                        );
                      })}
                      <Pressable onPress={() => removeEndpoint(i)} hitSlop={8} style={styles.methodChipRemove}>
                        <X size={16} color={colors.textTertiary} />
                      </Pressable>
                    </View>
                    <TextInput
                      value={endpoint.path}
                      onChangeText={(v) => updateEndpoint(i, { path: v })}
                      placeholder="/resource"
                      placeholderTextColor={colors.textTertiary}
                      autoCapitalize="none"
                      autoCorrect={false}
                      style={[styles.input, styles.mono, { color: colors.textPrimary, borderColor: colors.border, marginTop: 8 }]}
                    />
                    <TextInput
                      value={endpoint.purpose}
                      onChangeText={(v) => updateEndpoint(i, { purpose: v })}
                      placeholder="What this endpoint does"
                      placeholderTextColor={colors.textTertiary}
                      style={[styles.input, { color: colors.textSecondary, borderColor: colors.border, marginTop: 6 }]}
                    />
                  </View>
                ))}
                <Pressable onPress={addEndpoint} style={[styles.addRow, { borderColor: colors.border }]}>
                  <Plus size={14} color={colors.textSecondary} />
                  <Text style={{ color: colors.textSecondary, fontSize: 12, fontWeight: "600" }}>Add endpoint</Text>
                </Pressable>
              </>
            ) : (
              architecture.api_endpoints.map((endpoint, i) => (
                <View key={i} style={[styles.endpointRow, { backgroundColor: colors.background, borderColor: colors.border }]}>
                  <View
                    style={[
                      styles.methodBadge,
                      { backgroundColor: METHOD_COLORS[endpoint.method.toUpperCase()] || colors.textTertiary },
                    ]}
                  >
                    <Text style={styles.methodText}>{endpoint.method.toUpperCase()}</Text>
                  </View>
                  <Text style={[styles.mono, { color: colors.textPrimary, fontSize: 11 }]}>{endpoint.path}</Text>
                  <Text style={{ color: colors.textTertiary, fontSize: 11, flex: 1 }} numberOfLines={1}>
                    {endpoint.purpose}
                  </Text>
                </View>
              ))
            )}
          </Section>

          {isEditing && (
            <View style={[styles.saveBar, { borderColor: colors.border, backgroundColor: colors.surface }]}>
              {saveError && (
                <View style={[styles.saveError, { borderColor: colors.error, backgroundColor: `${colors.error}1a` }]}>
                  <AlertTriangle size={14} color={colors.error} style={{ marginTop: 1 }} />
                  <Text selectable style={{ color: colors.textPrimary, fontSize: 12, lineHeight: 18, flex: 1 }}>
                    {saveError}
                  </Text>
                  <Pressable onPress={() => setSaveError(null)} hitSlop={8} accessibilityLabel="Dismiss">
                    <X size={14} color={colors.textTertiary} />
                  </Pressable>
                </View>
              )}
              <View style={{ marginBottom: 6 }}>
                <LiveValidationStatus state={liveCheck} onShowIssues={showLiveIssues} />
              </View>
              <Text style={{ color: colors.textTertiary, fontSize: 11, marginBottom: 10 }}>
                Saving will require re-approval before the next code generation.
              </Text>
              <View style={styles.saveBarRow}>
                <Pressable
                  onPress={cancelEditing}
                  disabled={isSavingEdit}
                  style={[styles.saveBarButton, { borderColor: colors.border }, isSavingEdit && { opacity: 0.6 }]}
                >
                  <XCircle size={14} color={colors.textPrimary} />
                  <Text style={{ color: colors.textPrimary, fontSize: 13, fontWeight: "600" }}>Cancel</Text>
                </Pressable>
                <Pressable
                  onPress={saveEdits}
                  disabled={isSavingEdit}
                  style={[styles.saveBarButton, styles.saveBarPrimary, { backgroundColor: colors.primary }, isSavingEdit && { opacity: 0.6 }]}
                >
                  {isSavingEdit ? <ActivityIndicator size="small" color="#fff" /> : <Save size={14} color="#fff" />}
                  <Text style={{ color: "#fff", fontSize: 13, fontWeight: "700" }}>Save Changes</Text>
                </Pressable>
              </View>
            </View>
          )}

          {architecture.third_party_services.length > 0 && (
            <Section icon={Package} title="Third-Party Services">
              <View style={styles.pillRow}>
                {architecture.third_party_services.map((service, i) => (
                  <View key={i} style={[styles.pill, { backgroundColor: colors.primaryLight }]}>
                    <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "600" }}>{service}</Text>
                  </View>
                ))}
              </View>
              <Text style={{ color: colors.textTertiary, fontSize: 11, marginTop: 10, lineHeight: 16 }}>
                Open-source and free options are chosen by default — a paid service only appears here
                if you said you already have your own account for it.
              </Text>
            </Section>
          )}

          {architecture.adrs && architecture.adrs.length > 0 && (
            <Section icon={GitBranch} title={`Decision Records (${architecture.adrs.length})`}>
              {architecture.adrs.map((adr, i) => (
                <View key={i} style={[styles.stackCard, { borderColor: colors.border, backgroundColor: colors.surface }]}>
                  <Text style={{ color: colors.textPrimary, fontSize: 13, fontWeight: "700", marginBottom: 6 }}>
                    {adr.title}
                  </Text>
                  <Text style={[styles.body, { color: colors.textSecondary, marginBottom: 4 }]}>
                    <Text style={{ color: colors.primary, fontWeight: "600" }}>Decision: </Text>
                    {adr.decision}
                  </Text>
                  <Text style={[styles.body, { color: colors.textSecondary }]}>
                    <Text style={{ color: colors.primary, fontWeight: "600" }}>Why: </Text>
                    {adr.rationale}
                  </Text>
                  {adr.alternatives_considered?.length > 0 && (
                    <View style={[styles.pillRow, { marginTop: 8 }]}>
                      <Text style={{ color: colors.textTertiary, fontSize: 11 }}>Also considered:</Text>
                      {adr.alternatives_considered.map((alt, j) => (
                        <View key={j} style={[styles.fieldPill, { borderColor: colors.border }]}>
                          <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{alt}</Text>
                        </View>
                      ))}
                    </View>
                  )}
                </View>
              ))}
            </Section>
          )}

          {(blueprint.system_diagram || erdToShow) && (
            <Section icon={Network} title="Blueprint Diagrams">
              <Text style={{ color: colors.textTertiary, fontSize: 11, marginBottom: 10, lineHeight: 16 }}>
                Built directly from the architecture above — not a separate AI guess, so they can't
                disagree with it. This is Mermaid source: long-press to copy, then paste anywhere
                Mermaid renders (GitHub, Notion, mermaid.live).
              </Text>
              {blueprint.system_diagram ? (
                <DiagramBlock label="System diagram" code={blueprint.system_diagram} />
              ) : null}
              {erdToShow ? (
                <DiagramBlock
                  label={previewErd ? "Database ERD — preview of your unsaved edits" : "Database ERD"}
                  code={erdToShow}
                />
              ) : null}
            </Section>
          )}
        </ScrollView>
      </PendingEditsContext.Provider>

      <PhaseFooter
        note="Review the architecture above. Once approved, Baby Tiger starts building 🚀"
        secondaryActions={[{ label: "Export Docs", icon: BookOpen, onPress: handleDownloadDocs, loading: isDownloadingDocs }]}
        primaryLabel="Approve & Continue"
        primaryIcon={ThumbsUp}
        onPrimaryPress={handleApprove}
        primaryLoading={isApproving}
      />
    </KeyboardAvoidingView>
  );
}

function EditButton({ onPress }: { onPress: () => void }) {
  const { colors } = useTheme();
  return (
    <Pressable onPress={onPress} style={styles.editButton} hitSlop={8}>
      <Pencil size={12} color={colors.primary} />
      <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "600" }}>Edit</Text>
    </Pressable>
  );
}

/** Mermaid source in a scrollable monospace block. Not rendered to a real
 * diagram: that would mean shipping mermaid.js in the app bundle for two
 * small diagrams. `selectable` gives native long-press-to-copy, so no
 * clipboard dependency is needed either. */
function DiagramBlock({ label, code }: { label: string; code: string }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.diagramBlock, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "700", marginBottom: 6 }}>{label}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <Text selectable style={[styles.mono, { color: colors.textSecondary, fontSize: 11, lineHeight: 16 }]}>
          {code}
        </Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { padding: 16 },
  diagramBlock: { borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 10 },
  body: { fontSize: 13, lineHeight: 19 },
  help: { fontSize: 11, lineHeight: 16, marginBottom: 10 },
  mono: { fontFamily: "monospace" },
  stackCard: { borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 10 },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 10 },
  fieldPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, borderWidth: 1 },
  endpointRow: { flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 8 },
  methodBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6 },
  methodText: { color: "#fff", fontSize: 10, fontWeight: "700" },
  editButton: { flexDirection: "row", alignItems: "center", gap: 4 },
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 12 },
  addRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderWidth: 1, borderStyle: "dashed", borderRadius: 10, paddingVertical: 10, marginTop: 4 },
  checkRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 10,
    paddingVertical: 8,
    marginBottom: 10,
  },
  checkButton: { flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6 },
  editEndpointRow: { borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 8 },
  methodChipRow: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },
  methodChip: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, borderWidth: 1 },
  methodChipRemove: { marginLeft: "auto" },
  saveBar: { borderWidth: 1, borderRadius: 14, padding: 14, marginBottom: 16 },
  saveError: { flexDirection: "row", alignItems: "flex-start", gap: 8, borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 10 },
  saveBarRow: { flexDirection: "row", gap: 10 },
  saveBarButton: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderWidth: 1, borderRadius: 10, paddingVertical: 10 },
  saveBarPrimary: { borderWidth: 0 },
});
