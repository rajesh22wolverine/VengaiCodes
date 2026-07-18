import { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { AlertTriangle, ArrowLeft, BookOpen, FileCode2, Target, ThumbsUp } from "lucide-react-native";

import apiClient from "@/lib/api";
import { downloadAndShareFile } from "@/lib/download";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import PhaseHeader from "@/components/phase/PhaseHeader";
import PhaseLoading from "@/components/phase/PhaseLoading";
import PhaseFooter from "@/components/phase/PhaseFooter";

interface GeneratedTestFile {
  path: string;
  language: string;
  content: string;
  description: string;
  tests_what: string;
}

interface TestPlanResult {
  summary: string;
  test_files: GeneratedTestFile[];
  coverage_notes: string;
}

const LANGUAGE_COLORS: Record<string, string> = {
  python: "#38bdf8",
  typescript: "#f97316",
  javascript: "#eab308",
  tsx: "#f97316",
  jsx: "#eab308",
};

export default function TestingScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [testing, setTesting] = useState<TestPlanResult | null>(null);
  const [selectedFile, setSelectedFile] = useState<GeneratedTestFile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/testing/${projectId}`);
      setTesting(data.testing);
      setIsLoading(false);
    } catch {
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/testing/generate", { project_id: projectId });
      setTesting(data.testing);
      showToast("Your test stubs are ready! 🧪🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to generate tests.", "error");
      router.replace(`/(app)/project/${projectId}/codegen` as any);
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
      await apiClient.post("/testing/approve", { project_id: projectId, approved: true });
      showToast("Tests approved! Next: Export 🐯");
      router.replace(`/(app)/project/${projectId}/export` as any);
    } catch (error: any) {
      showToast(error.message || "Failed to approve.", "error");
    } finally {
      setIsApproving(false);
    }
  };

  if (isLoading || isGenerating) {
    return <PhaseLoading message={isGenerating ? "Baby Tiger is writing your tests... 🧪🐯" : "Loading..."} />;
  }

  if (!testing) return null;

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <PhaseHeader
        title="Testing"
        subtitle={`Phase 5 of 7 — ${testing.test_files.length} test file${testing.test_files.length === 1 ? "" : "s"} generated`}
      />

      <View style={[styles.summaryBanner, { backgroundColor: colors.primaryLight, borderBottomColor: colors.border }]}>
        <Text style={{ color: colors.primary, fontSize: 12, lineHeight: 17 }}>{testing.summary}</Text>
      </View>

      <View style={[styles.warningBanner, { borderBottomColor: colors.border }]}>
        <AlertTriangle size={14} color="#eab308" style={{ marginTop: 1 }} />
        <Text style={{ color: colors.textSecondary, fontSize: 12, flex: 1, lineHeight: 17 }}>
          <Text style={{ fontWeight: "700", color: colors.textPrimary }}>Coverage notes: </Text>
          {testing.coverage_notes}
        </Text>
      </View>

      {selectedFile ? (
        <View style={styles.flex}>
          <Pressable onPress={() => setSelectedFile(null)} style={styles.backToFilesRow}>
            <ArrowLeft size={14} color={colors.textSecondary} />
            <Text style={{ color: colors.textSecondary, fontSize: 12 }}>Back to files</Text>
          </Pressable>
          <View style={[styles.fileMetaBox, { borderBottomColor: colors.border }]}>
            <Text style={[styles.mono, { color: colors.textTertiary, fontSize: 11 }]}>{selectedFile.path}</Text>
            <Text style={{ color: colors.textSecondary, fontSize: 12, marginTop: 4 }}>{selectedFile.description}</Text>
            <View style={styles.testsWhatRow}>
              <Target size={11} color={colors.textTertiary} />
              <Text style={[styles.mono, { color: colors.textTertiary, fontSize: 11 }]}>Tests: {selectedFile.tests_what}</Text>
            </View>
          </View>
          <ScrollView style={styles.flex} contentContainerStyle={styles.codeScroll}>
            <ScrollView horizontal>
              <Text style={[styles.mono, styles.code, { color: colors.textPrimary, backgroundColor: colors.surface }]}>
                {selectedFile.content}
              </Text>
            </ScrollView>
          </ScrollView>
        </View>
      ) : (
        <ScrollView style={styles.flex} contentContainerStyle={styles.fileListContent}>
          {testing.test_files.map((file, i) => (
            <Pressable
              key={i}
              onPress={() => setSelectedFile(file)}
              style={[styles.fileRow, { borderColor: colors.border, backgroundColor: colors.surface }]}
            >
              <FileCode2 size={16} color={LANGUAGE_COLORS[file.language] || colors.textTertiary} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.mono, { color: colors.textPrimary, fontSize: 12, fontWeight: "600" }]} numberOfLines={1}>
                  {file.path}
                </Text>
                <Text style={{ color: colors.textTertiary, fontSize: 11 }} numberOfLines={1}>
                  {file.description}
                </Text>
              </View>
            </Pressable>
          ))}
        </ScrollView>
      )}

      <PhaseFooter
        note="These are test stubs, not verified passing tests — review, then continue to Export 📦"
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
  flex: { flex: 1 },
  summaryBanner: { padding: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  warningBanner: { flexDirection: "row", gap: 8, padding: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  fileListContent: { padding: 12 },
  fileRow: { flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 8 },
  backToFilesRow: { flexDirection: "row", alignItems: "center", gap: 6, padding: 12 },
  fileMetaBox: { paddingHorizontal: 12, paddingBottom: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  testsWhatRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6 },
  mono: { fontFamily: "monospace" },
  codeScroll: { padding: 12 },
  code: { fontSize: 11, lineHeight: 16, padding: 12, borderRadius: 10 },
});
