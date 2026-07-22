import { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { AlertTriangle, ArrowLeft, BookOpen, Download, FileCode2, ThumbsUp } from "lucide-react-native";

import apiClient from "@/lib/api";
import { downloadAndShareFile } from "@/lib/download";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import PhaseHeader from "@/components/phase/PhaseHeader";
import PhaseLoading from "@/components/phase/PhaseLoading";
import PhaseFooter from "@/components/phase/PhaseFooter";

interface GeneratedFile {
  path: string;
  language: string;
  content: string;
  description: string;
}

interface CodeGenResult {
  summary: string;
  files: GeneratedFile[];
}

interface StackUsed {
  codegen_target: string;
  source: string;
  fallback_reason: string | null;
}

const WARNING_COLOR = "#eab308";

const LANGUAGE_COLORS: Record<string, string> = {
  python: "#38bdf8",
  typescript: "#f97316",
  javascript: "#eab308",
  tsx: "#f97316",
  jsx: "#eab308",
  json: "#a1a1aa",
};

export default function CodeGenScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [codegen, setCodegen] = useState<CodeGenResult | null>(null);
  const [stackUsed, setStackUsed] = useState<StackUsed | null>(null);
  const [selectedFile, setSelectedFile] = useState<GeneratedFile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/codegen/${projectId}`);
      setCodegen(data.codegen);
      setStackUsed(data.stack_used || null);
      setIsLoading(false);
    } catch {
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/codegen/generate", { project_id: projectId });
      setCodegen(data.codegen);
      setStackUsed(data.stack_used || null);
      showToast("Your code is ready! 💻🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to generate code.", "error");
      router.replace(`/(app)/project/${projectId}/architecture` as any);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownload = async () => {
    setIsDownloading(true);
    try {
      await downloadAndShareFile(`/export/${projectId}/download`, "vengaicode_export.zip");
      showToast("Downloaded! Check your Files app 🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to download files.", "error");
    } finally {
      setIsDownloading(false);
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
      await apiClient.post("/codegen/approve", { project_id: projectId, approved: true });
      showToast("Code approved! Next: Testing 🐯");
      router.replace(`/(app)/project/${projectId}/testing` as any);
    } catch (error: any) {
      showToast(error.message || "Failed to approve.", "error");
    } finally {
      setIsApproving(false);
    }
  };

  if (isLoading || isGenerating) {
    return <PhaseLoading message={isGenerating ? "Baby Tiger is writing your code... 💻🐯" : "Loading..."} />;
  }

  if (!codegen) return null;

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <PhaseHeader
        title="Code Generation"
        subtitle={`Phase 4 of 7 — ${codegen.files.length} file${codegen.files.length === 1 ? "" : "s"} generated`}
      />

      <View style={[styles.summaryBanner, { backgroundColor: colors.primaryLight, borderBottomColor: colors.border }]}>
        <Text style={{ color: colors.primary, fontSize: 12, lineHeight: 17 }}>{codegen.summary}</Text>
      </View>

      {stackUsed?.fallback_reason && (
        <View style={[styles.warningBanner, { borderBottomColor: colors.border }]}>
          <AlertTriangle size={14} color={WARNING_COLOR} style={{ marginTop: 1 }} />
          <Text style={{ color: colors.textSecondary, fontSize: 12, flex: 1, lineHeight: 17 }}>
            {stackUsed.fallback_reason}
          </Text>
        </View>
      )}

      {selectedFile ? (
        <View style={styles.flex}>
          <Pressable onPress={() => setSelectedFile(null)} style={styles.backToFilesRow}>
            <ArrowLeft size={14} color={colors.textSecondary} />
            <Text style={{ color: colors.textSecondary, fontSize: 12 }}>Back to files</Text>
          </Pressable>
          <View style={[styles.fileMetaBox, { borderBottomColor: colors.border }]}>
            <Text style={[styles.mono, { color: colors.textTertiary, fontSize: 11 }]}>{selectedFile.path}</Text>
            <Text style={{ color: colors.textSecondary, fontSize: 12, marginTop: 4 }}>{selectedFile.description}</Text>
          </View>
          <ScrollView style={styles.flex} contentContainerStyle={styles.codeScroll} horizontal={false}>
            <ScrollView horizontal>
              <Text style={[styles.mono, styles.code, { color: colors.textPrimary, backgroundColor: colors.surface }]}>
                {selectedFile.content}
              </Text>
            </ScrollView>
          </ScrollView>
        </View>
      ) : (
        <ScrollView style={styles.flex} contentContainerStyle={styles.fileListContent}>
          {codegen.files.map((file, i) => (
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
        note="This is a starter skeleton — review the structure, then continue to Testing 🧪"
        secondaryActions={[
          { label: "Export Docs", icon: BookOpen, onPress: handleDownloadDocs, loading: isDownloadingDocs },
          { label: "Download ZIP", icon: Download, onPress: handleDownload, loading: isDownloading },
        ]}
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
  mono: { fontFamily: "monospace" },
  codeScroll: { padding: 12 },
  code: { fontSize: 11, lineHeight: 16, padding: 12, borderRadius: 10 },
});
