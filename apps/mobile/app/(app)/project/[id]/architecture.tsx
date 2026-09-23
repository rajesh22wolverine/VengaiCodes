import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import {
  BookOpen, Database, GitBranch, Layers, Network, Package, Pencil, Plus,
  Save, ThumbsUp, Webhook, X, XCircle,
} from "lucide-react-native";

import apiClient from "@/lib/api";
import { downloadAndShareFile } from "@/lib/download";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import PhaseHeader from "@/components/phase/PhaseHeader";
import PhaseLoading from "@/components/phase/PhaseLoading";
import PhaseFooter from "@/components/phase/PhaseFooter";
import Section from "@/components/ui/Section";

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

/** Mermaid source the backend builds deterministically from the
 * architecture above (no second AI call), so it can't contradict it. */
interface Blueprint {
  system_diagram?: string | null;
  erd?: string | null;
}

const METHOD_COLORS: Record<string, string> = {
  GET: "#22c55e",
  POST: "#f97316",
  PUT: "#eab308",
  PATCH: "#eab308",
  DELETE: "#ef4444",
};

const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"];

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
      const { data } = await apiClient.post("/architecture/generate", { project_id: projectId });
      setArchitecture(data.architecture);
      // The generate response carries the design itself; the deterministic
      // diagrams are built alongside it and come back on the GET.
      try {
        const { data: saved } = await apiClient.get(`/architecture/${projectId}`);
        setBlueprint({ system_diagram: saved.system_diagram, erd: saved.erd });
      } catch {
        setBlueprint({});
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

  const startEditing = () => {
    if (!architecture) return;
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
      showToast("Changes saved — review and approve again to continue 🐯");
    } catch (error: any) {
      showToast(error.response?.data?.detail || error.message || "Failed to save changes.", "error");
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
    return <PhaseLoading message={isGenerating ? "Baby Tiger is planning your architecture... 🏗️🐯" : "Loading..."} />;
  }

  if (!architecture) return null;

  const stackEntries = Object.entries(architecture.tech_stack) as [keyof TechStack, string][];

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <PhaseHeader title="Architecture" subtitle="Phase 3 of 7 — Review and approve to continue" />

      <ScrollView contentContainerStyle={styles.content}>
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

        <Section
          icon={Database}
          title={`Database Tables (${(isEditing ? draftTables : architecture.database_tables).length})`}
          action={!isEditing && <EditButton onPress={startEditing} />}
        >
          {isEditing ? (
            <>
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
              <Pressable
                onPress={addTable}
                style={[styles.addRow, { borderColor: colors.border }]}
              >
                <Plus size={14} color={colors.textSecondary} />
                <Text style={{ color: colors.textSecondary, fontSize: 12, fontWeight: "600" }}>Add table</Text>
              </Pressable>
            </>
          ) : (
            architecture.database_tables.map((table, i) => (
              <View key={i} style={[styles.stackCard, { backgroundColor: colors.background, borderColor: colors.border }]}>
                <View style={styles.rowGap}>
                  <Database size={13} color={colors.primary} />
                  <Text style={[styles.mono, { color: colors.textPrimary, fontWeight: "700" }]}>{table.name}</Text>
                </View>
                <Text style={[styles.body, { color: colors.textSecondary, marginVertical: 8 }]}>{table.purpose}</Text>
                <View style={styles.pillRow}>
                  {table.key_fields.map((field, j) => (
                    <View key={j} style={[styles.fieldPill, { backgroundColor: colors.surface, borderColor: colors.border }]}>
                      <Text style={[styles.mono, { color: colors.textTertiary, fontSize: 11 }]}>{field}</Text>
                    </View>
                  ))}
                </View>
              </View>
            ))
          )}
        </Section>

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
              <Pressable
                onPress={addEndpoint}
                style={[styles.addRow, { borderColor: colors.border }]}
              >
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

        {(blueprint.system_diagram || blueprint.erd) && (
          <Section icon={Network} title="Blueprint Diagrams">
            <Text style={{ color: colors.textTertiary, fontSize: 11, marginBottom: 10, lineHeight: 16 }}>
              Built directly from the architecture above — not a separate AI guess, so they can't
              disagree with it. This is Mermaid source: long-press to copy, then paste anywhere
              Mermaid renders (GitHub, Notion, mermaid.live).
            </Text>
            {blueprint.system_diagram ? (
              <DiagramBlock label="System diagram" code={blueprint.system_diagram} />
            ) : null}
            {blueprint.erd ? <DiagramBlock label="Database ERD" code={blueprint.erd} /> : null}
          </Section>
        )}
      </ScrollView>

      <PhaseFooter
        note="Review the architecture above. Once approved, Baby Tiger starts building 🚀"
        secondaryActions={[{ label: "Export Docs", icon: BookOpen, onPress: handleDownloadDocs, loading: isDownloadingDocs }]}
        primaryLabel="Approve & Continue"
        primaryIcon={ThumbsUp}
        onPrimaryPress={handleApprove}
        primaryLoading={isApproving}
      />
    </View>
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

/** One editable table card: name, purpose, and a chip list of fields
 * with per-field remove + an inline "add field" input (submit to add). */
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
  const { colors } = useTheme();
  const [newField, setNewField] = useState("");

  const commitField = () => {
    if (!newField.trim()) return;
    onAddField(newField);
    setNewField("");
  };

  return (
    <View style={[styles.stackCard, { backgroundColor: colors.background, borderColor: colors.border }]}>
      <View style={styles.editTableTopRow}>
        <TextInput
          value={table.name}
          onChangeText={(v) => onChange({ name: v })}
          placeholder="table_name"
          placeholderTextColor={colors.textTertiary}
          style={[styles.input, styles.mono, { flex: 1, color: colors.textPrimary, borderColor: colors.border, fontWeight: "700" }]}
        />
        <Pressable onPress={onRemove} hitSlop={8}>
          <X size={16} color={colors.textTertiary} />
        </Pressable>
      </View>
      <TextInput
        value={table.purpose}
        onChangeText={(v) => onChange({ purpose: v })}
        placeholder="What this table is for"
        placeholderTextColor={colors.textTertiary}
        style={[styles.input, { color: colors.textSecondary, borderColor: colors.border, marginTop: 8 }]}
      />
      <View style={[styles.pillRow, { marginTop: 10 }]}>
        {table.key_fields.map((field, j) => (
          <View key={j} style={[styles.editFieldPill, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <Text style={[styles.mono, { color: colors.textTertiary, fontSize: 11 }]}>{field}</Text>
            <Pressable onPress={() => onRemoveField(j)} hitSlop={6}>
              <X size={11} color={colors.textTertiary} />
            </Pressable>
          </View>
        ))}
      </View>
      <TextInput
        value={newField}
        onChangeText={setNewField}
        onSubmitEditing={commitField}
        onBlur={commitField}
        placeholder="+ add field"
        placeholderTextColor={colors.textTertiary}
        style={[styles.input, styles.mono, { color: colors.textSecondary, borderColor: colors.border, borderStyle: "dashed", marginTop: 8 }]}
      />
    </View>
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
  mono: { fontFamily: "monospace" },
  stackCard: { borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 10 },
  rowGap: { flexDirection: "row", alignItems: "center", gap: 8 },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 10 },
  fieldPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, borderWidth: 1 },
  endpointRow: { flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 8 },
  methodBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6 },
  methodText: { color: "#fff", fontSize: 10, fontWeight: "700" },
  editButton: { flexDirection: "row", alignItems: "center", gap: 4 },
  input: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 12 },
  addRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderWidth: 1, borderStyle: "dashed", borderRadius: 10, paddingVertical: 10, marginTop: 4 },
  editTableTopRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  editFieldPill: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, borderWidth: 1 },
  editEndpointRow: { borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 8 },
  methodChipRow: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" },
  methodChip: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, borderWidth: 1 },
  methodChipRemove: { marginLeft: "auto" },
  saveBar: { borderWidth: 1, borderRadius: 14, padding: 14, marginBottom: 16 },
  saveBarRow: { flexDirection: "row", gap: 10 },
  saveBarButton: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderWidth: 1, borderRadius: 10, paddingVertical: 10 },
  saveBarPrimary: { borderWidth: 0 },
});
