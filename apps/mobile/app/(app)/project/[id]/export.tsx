import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Linking, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Code2,
  Download,
  ExternalLink,
  FileText,
  Layers,
  Monitor,
  Package,
  PartyPopper,
  TestTube2,
  Palette,
} from "lucide-react-native";

import apiClient from "@/lib/api";
import { downloadAndShareFile } from "@/lib/download";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import TextField from "@/components/ui/TextField";
import BabyTiger from "@/components/BabyTiger";

type BuildStatus = "idle" | "queued" | "in_progress" | "completed" | "failed";

interface ProjectSummary {
  name: string;
  files_generated: number;
  tests_generated: number;
  platforms: string[];
}

interface BuildArtifact {
  name: string;
  size_bytes: number;
  id: number;
}

const POLL_INTERVAL_MS = 15000;
const POLL_TIMEOUT_MS = 25 * 60 * 1000;

export default function ExportScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);
  const [includeO3DE, setIncludeO3DE] = useState(false);
  const [appName, setAppName] = useState("");

  const [buildStatus, setBuildStatus] = useState<BuildStatus>("idle");
  const [buildRunUrl, setBuildRunUrl] = useState<string | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [artifacts, setArtifacts] = useState<BuildArtifact[]>([]);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollStartedAtRef = useRef<number | null>(null);

  useEffect(() => {
    loadSummary();
    return () => stopPolling();
  }, [projectId]);

  const loadSummary = async () => {
    try {
      const { data } = await apiClient.get(`/projects/${projectId}`);
      setSummary({
        name: data.project.name,
        files_generated: data.project.codegen_data?.codegen?.files?.length || 0,
        tests_generated: data.project.testing_data?.testing?.test_files?.length || 0,
        platforms: data.project.platforms || [],
      });
      setAppName(data.project.name || "");
    } catch {
      showToast("Failed to load project summary.", "error");
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownload = async () => {
    setIsDownloading(true);
    try {
      const filename = `${(appName || summary?.name || "vengaicode_project").trim()}.zip`;
      await downloadAndShareFile(`/export/${projectId}/download`, filename, {
        include_o3de: includeO3DE,
        app_name: appName.trim() || undefined,
      });
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

  const handleFinish = async () => {
    try {
      await apiClient.post(`/projects/${projectId}/complete`);
      showToast("Nice work! Your project is saved in Completed 🐯");
    } catch {
      showToast("Returning home 🐯");
    } finally {
      router.replace("/(app)/(tabs)/home");
    }
  };

  const stopPolling = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  const checkBuildStatus = async () => {
    try {
      const { data } = await apiClient.get(`/packaging/${projectId}/status`);
      setBuildRunUrl(data.run_url || null);

      if (data.status === "completed") {
        stopPolling();
        if (data.conclusion === "success") {
          setBuildStatus("completed");
          showToast("Your installer is ready! 🐯🎉");
          fetchArtifacts();
        } else {
          setBuildStatus("failed");
          showToast("Build failed. Check the build log for details.", "error");
        }
        return;
      }

      setBuildStatus(data.status === "queued" ? "queued" : "in_progress");

      if (pollStartedAtRef.current && Date.now() - pollStartedAtRef.current > POLL_TIMEOUT_MS) {
        stopPolling();
        showToast("Build is taking longer than expected. Check the log directly.", "error");
      }
    } catch {
      // Don't stop polling on a single failed check — transient errors happen
    }
  };

  const fetchArtifacts = async () => {
    try {
      const { data } = await apiClient.get(`/packaging/${projectId}/artifacts`);
      setArtifacts(data.artifacts || []);
    } catch {
      // Non-fatal — build succeeded, artifact listing is best-effort
    }
  };

  const downloadArtifact = async (artifactId: number, name: string) => {
    try {
      await downloadAndShareFile(`/packaging/${projectId}/artifacts/${artifactId}/download`, `${name}.zip`);
      showToast("Downloaded! Extract the ZIP to find your installer 🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to download installer.", "error");
    }
  };

  const handleTriggerBuild = async () => {
    setIsTriggering(true);
    try {
      await apiClient.post("/packaging/build", { project_id: projectId });
      showToast("Build started! This takes 5-15 minutes 🐯🏗️");
      setBuildStatus("queued");
      pollStartedAtRef.current = Date.now();
      stopPolling();
      pollIntervalRef.current = setInterval(checkBuildStatus, POLL_INTERVAL_MS);
      checkBuildStatus();
    } catch (error: any) {
      showToast(error.message || "Failed to start build. Windows packaging may not be configured yet.", "error");
      setBuildStatus("idle");
    } finally {
      setIsTriggering(false);
    }
  };

  if (isLoading) {
    return (
      <View style={[styles.centered, { backgroundColor: colors.background }]}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <View style={[styles.header, { borderBottomColor: colors.border, backgroundColor: colors.surface }]}>
        <Pressable onPress={() => router.push("/(app)/(tabs)/home")} hitSlop={8}>
          <ArrowLeft size={18} color={colors.textSecondary} />
        </Pressable>
        <BabyTiger size={28} expression="celebrating" />
        <View style={{ flex: 1 }}>
          <Text style={[styles.headerTitle, { color: colors.textPrimary }]}>Export</Text>
          <Text style={[styles.headerSubtitle, { color: colors.textTertiary }]}>
            Phase 6 of 7 — Your project is ready to download
          </Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        <View style={styles.celebrationBlock}>
          <Text style={styles.celebrationEmoji}>🐯🎉</Text>
          <Text style={[styles.celebrationTitle, { color: colors.textPrimary }]}>
            {summary?.name || "Your project"} is ready! 🎉
          </Text>
          <Text style={[styles.celebrationSubtitle, { color: colors.textSecondary }]}>
            Baby Tiger built your requirements, design, architecture, code, and tests. Download everything below.
          </Text>
        </View>

        <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <Text style={[styles.cardTitle, { color: colors.textPrimary }]}>What was built</Text>
          <JourneyItem icon={FileText} label="Requirements Document" colors={colors} />
          <JourneyItem icon={Palette} label="UI/UX Design System" colors={colors} />
          <JourneyItem icon={Layers} label="Technical Architecture" colors={colors} />
          <JourneyItem icon={Code2} label={`Starter Code (${summary?.files_generated || 0} files)`} colors={colors} />
          <JourneyItem icon={TestTube2} label={`Test Stubs (${summary?.tests_generated || 0} files)`} colors={colors} />
        </View>

        <View style={[styles.card, { borderColor: "#eab308", backgroundColor: colors.primaryLight }]}>
          <Text style={{ color: colors.textSecondary, fontSize: 12, lineHeight: 18 }}>
            <Text style={{ fontWeight: "700", color: colors.textPrimary }}>Good to know: </Text>
            The ZIP contains a starter code skeleton and test stubs — not a finished application. The Windows
            installer below packages the generated frontend as a desktop app shell; it does not yet bundle a working
            backend server.
          </Text>
        </View>

        <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <View style={styles.cardHeaderRow}>
            <Download size={16} color={colors.primary} />
            <Text style={[styles.cardTitle, { color: colors.textPrimary, marginBottom: 0 }]}>Export your app</Text>
          </View>

          <TextField label="App name" placeholder="Enter your app name" value={appName} onChangeText={setAppName} />

          <Pressable style={styles.checkboxRow} onPress={() => setIncludeO3DE((v) => !v)}>
            <View
              style={[
                styles.checkbox,
                { borderColor: colors.border },
                includeO3DE ? { backgroundColor: colors.primary, borderColor: colors.primary } : null,
              ]}
            />
            <Text style={{ color: colors.textSecondary, fontSize: 12, flex: 1 }}>
              Include O3DE template files (experimental)
            </Text>
          </Pressable>

          <Pressable
            onPress={handleDownload}
            disabled={isDownloading}
            style={[styles.primaryButton, { backgroundColor: colors.primary }, isDownloading && { opacity: 0.6 }]}
          >
            {isDownloading ? <ActivityIndicator color="#fff" size="small" /> : <Download size={15} color="#fff" />}
            <Text style={styles.primaryButtonText}>Download Project ZIP</Text>
          </Pressable>

          <Pressable
            onPress={handleDownloadDocs}
            disabled={isDownloadingDocs}
            style={[styles.outlineButton, { borderColor: colors.border }, isDownloadingDocs && { opacity: 0.6 }]}
          >
            {isDownloadingDocs ? (
              <ActivityIndicator color={colors.textPrimary} size="small" />
            ) : (
              <FileText size={15} color={colors.textPrimary} />
            )}
            <Text style={{ color: colors.textPrimary, fontWeight: "700", fontSize: 13 }}>Export Documentation</Text>
          </Pressable>

          <Pressable onPress={handleFinish} style={[styles.outlineButton, { borderColor: colors.border }]}>
            <PartyPopper size={15} color={colors.textPrimary} />
            <Text style={{ color: colors.textPrimary, fontWeight: "700", fontSize: 13 }}>Finish &amp; Return Home</Text>
          </Pressable>
        </View>

        <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <View style={styles.cardHeaderRow}>
            <Monitor size={16} color={colors.primary} />
            <Text style={[styles.cardTitle, { color: colors.textPrimary, marginBottom: 0 }]}>Windows Installer</Text>
            <View style={[styles.experimentalBadge, { backgroundColor: colors.primaryLight }]}>
              <Text style={{ color: colors.primary, fontSize: 10, fontWeight: "700" }}>Experimental</Text>
            </View>
          </View>

          {buildStatus === "idle" && (
            <>
              <Text style={{ color: colors.textSecondary, fontSize: 12, lineHeight: 18, marginBottom: 12 }}>
                Build a real Windows .msi/.exe installer from your generated frontend. This takes 5-15 minutes and
                requires packaging to be configured on the backend.
              </Text>
              <Pressable
                onPress={handleTriggerBuild}
                disabled={isTriggering}
                style={[styles.outlinePrimaryButton, { borderColor: colors.primary }, isTriggering && { opacity: 0.6 }]}
              >
                {isTriggering ? (
                  <ActivityIndicator color={colors.primary} size="small" />
                ) : (
                  <Package size={15} color={colors.primary} />
                )}
                <Text style={{ color: colors.primary, fontWeight: "700", fontSize: 13 }}>Build Windows Installer</Text>
              </Pressable>
            </>
          )}

          {(buildStatus === "queued" || buildStatus === "in_progress") && (
            <View style={{ alignItems: "center", gap: 8, paddingVertical: 12 }}>
              <ActivityIndicator color={colors.primary} />
              <Text style={{ color: colors.textPrimary, fontWeight: "600", fontSize: 13 }}>
                {buildStatus === "queued" ? "Build queued..." : "Building your installer..."}
              </Text>
              <Text style={{ color: colors.textTertiary, fontSize: 11, textAlign: "center" }}>
                This usually takes 5-15 minutes. Feel free to leave this page — come back and check later.
              </Text>
              {buildRunUrl && (
                <Pressable onPress={() => Linking.openURL(buildRunUrl)} style={styles.linkRow}>
                  <Text style={{ color: colors.primary, fontSize: 12 }}>View live build log</Text>
                  <ExternalLink size={12} color={colors.primary} />
                </Pressable>
              )}
            </View>
          )}

          {buildStatus === "completed" && (
            <View style={{ gap: 10 }}>
              <View style={styles.rowGap}>
                <CheckCircle2 size={16} color={colors.success} />
                <Text style={{ color: colors.success, fontWeight: "600", fontSize: 13 }}>Build succeeded!</Text>
              </View>
              {artifacts.length > 0 ? (
                artifacts.map((artifact) => (
                  <View key={artifact.id} style={[styles.artifactRow, { borderColor: colors.border, backgroundColor: colors.background }]}>
                    <View style={{ flex: 1 }}>
                      <Text style={{ color: colors.textPrimary, fontSize: 12, fontFamily: "monospace" }} numberOfLines={1}>
                        {artifact.name}
                      </Text>
                      <Text style={{ color: colors.textTertiary, fontSize: 11 }}>
                        {(artifact.size_bytes / 1024 / 1024).toFixed(1)} MB
                      </Text>
                    </View>
                    <Pressable
                      onPress={() => downloadArtifact(artifact.id, artifact.name)}
                      style={[styles.smallButton, { backgroundColor: colors.primary }]}
                    >
                      <Download size={13} color="#fff" />
                      <Text style={{ color: "#fff", fontSize: 11, fontWeight: "700" }}>Download</Text>
                    </Pressable>
                  </View>
                ))
              ) : (
                <Text style={{ color: colors.textTertiary, fontSize: 12 }}>
                  Build succeeded but no artifact was found. Check the build log.
                </Text>
              )}
            </View>
          )}

          {buildStatus === "failed" && (
            <View style={{ gap: 10 }}>
              <View style={styles.rowGap}>
                <AlertCircle size={16} color={colors.error} />
                <Text style={{ color: colors.error, fontWeight: "600", fontSize: 13 }}>Build failed</Text>
              </View>
              <Text style={{ color: colors.textSecondary, fontSize: 12, lineHeight: 18 }}>
                Something went wrong during packaging — this is an experimental feature and failures are expected
                while it's being refined.
              </Text>
              {buildRunUrl && (
                <Pressable onPress={() => Linking.openURL(buildRunUrl)} style={styles.linkRow}>
                  <Text style={{ color: colors.primary, fontSize: 12 }}>View build log for details</Text>
                  <ExternalLink size={12} color={colors.primary} />
                </Pressable>
              )}
              <Pressable onPress={() => setBuildStatus("idle")} style={[styles.outlineButton, { borderColor: colors.border }]}>
                <Text style={{ color: colors.textPrimary, fontWeight: "700", fontSize: 13 }}>Try Again</Text>
              </Pressable>
            </View>
          )}
        </View>
      </ScrollView>
    </View>
  );
}

function JourneyItem({ icon: Icon, label, colors }: { icon: React.ElementType; label: string; colors: ReturnType<typeof useTheme>["colors"] }) {
  return (
    <View style={styles.journeyRow}>
      <View style={[styles.journeyIcon, { backgroundColor: colors.primaryLight }]}>
        <Icon size={15} color={colors.success} />
      </View>
      <Text style={{ color: colors.textPrimary, fontSize: 13, flex: 1 }}>{label}</Text>
      <CheckCircle2 size={15} color={colors.success} />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  centered: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  emoji: { fontSize: 20 },
  headerTitle: { fontSize: 14, fontWeight: "700" },
  headerSubtitle: { fontSize: 11 },
  content: { padding: 16 },
  celebrationBlock: { alignItems: "center", marginBottom: 20 },
  celebrationEmoji: { fontSize: 48, marginBottom: 8 },
  celebrationTitle: { fontSize: 19, fontWeight: "700", textAlign: "center", marginBottom: 6 },
  celebrationSubtitle: { fontSize: 13, textAlign: "center", lineHeight: 19 },
  card: { borderWidth: 1, borderRadius: 16, padding: 16, marginBottom: 16 },
  cardHeaderRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 14 },
  cardTitle: { fontSize: 14, fontWeight: "700", marginBottom: 12 },
  journeyRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 10 },
  journeyIcon: { width: 30, height: 30, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  checkboxRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 12, marginBottom: 16 },
  checkbox: { width: 18, height: 18, borderRadius: 5, borderWidth: 1.5 },
  primaryButton: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, borderRadius: 12, paddingVertical: 13, marginBottom: 10 },
  primaryButtonText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  outlineButton: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, borderWidth: 1, borderRadius: 12, paddingVertical: 13, marginBottom: 10 },
  outlinePrimaryButton: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, borderWidth: 1.5, borderRadius: 12, paddingVertical: 13 },
  experimentalBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  rowGap: { flexDirection: "row", alignItems: "center", gap: 8 },
  linkRow: { flexDirection: "row", alignItems: "center", gap: 4 },
  artifactRow: { flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderRadius: 10, padding: 10 },
  smallButton: { flexDirection: "row", alignItems: "center", gap: 4, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6 },
});
