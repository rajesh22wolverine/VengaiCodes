import { useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { BookOpen, Database, Layers, Package, ThumbsUp, Webhook } from "lucide-react-native";

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

interface ArchitectureDesign {
  architecture_summary: string;
  tech_stack: TechStack;
  database_tables: DatabaseTable[];
  api_endpoints: APIEndpoint[];
  third_party_services: string[];
}

const METHOD_COLORS: Record<string, string> = {
  GET: "#22c55e",
  POST: "#f97316",
  PUT: "#eab308",
  PATCH: "#eab308",
  DELETE: "#ef4444",
};

export default function ArchitectureScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [architecture, setArchitecture] = useState<ArchitectureDesign | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/architecture/${projectId}`);
      setArchitecture(data.architecture);
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

        <Section icon={Database} title={`Database Tables (${architecture.database_tables.length})`}>
          {architecture.database_tables.map((table, i) => (
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
          ))}
        </Section>

        <Section icon={Webhook} title={`API Endpoints (${architecture.api_endpoints.length})`}>
          {architecture.api_endpoints.map((endpoint, i) => (
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
          ))}
        </Section>

        {architecture.third_party_services.length > 0 && (
          <Section icon={Package} title="Third-Party Services">
            <View style={styles.pillRow}>
              {architecture.third_party_services.map((service, i) => (
                <View key={i} style={[styles.pill, { backgroundColor: colors.primaryLight }]}>
                  <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "600" }}>{service}</Text>
                </View>
              ))}
            </View>
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

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { padding: 16 },
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
});
