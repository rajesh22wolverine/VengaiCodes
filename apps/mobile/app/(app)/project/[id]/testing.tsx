import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import {
  AlertTriangle, ArrowLeft, BookOpen, CheckCircle2, FileCode2, FlaskConical,
  Play, Plus, RotateCcw, Target, ThumbsUp, Wrench, X, XCircle,
} from "lucide-react-native";

import apiClient from "@/lib/api";
import { downloadAndShareFile } from "@/lib/download";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import PhaseHeader from "@/components/phase/PhaseHeader";
import PhaseLoading from "@/components/phase/PhaseLoading";
import PhaseFooter from "@/components/phase/PhaseFooter";
import BabyTiger from "@/components/BabyTiger";

interface GeneratedTestFile {
  path: string;
  language: string;
  content: string;
  description: string;
  tests_what: string;
  framework?: string;
  source?: "auto" | "custom";
}

interface TestPlanResult {
  summary: string;
  test_files: GeneratedTestFile[];
  coverage_notes: string;
}

interface FrameworkOptions {
  detected_stack: string;
  options: string[];
  recommended: string;
}

interface SelectedFrameworks {
  backend: string;
  frontend: string;
}

interface TestFailure {
  file: string;
  test_name: string;
  message: string;
}

interface TestRunResults {
  passed: number;
  failed: number;
  total: number;
  failures: TestFailure[];
}

const LANGUAGE_COLORS: Record<string, string> = {
  python: "#38bdf8",
  typescript: "#f97316",
  javascript: "#eab308",
  tsx: "#f97316",
  jsx: "#eab308",
};

const MAX_AUTO_FIX_ATTEMPTS = 3;
const POLL_INTERVAL_MS = 8000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

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

  const [frontendOptions, setFrontendOptions] = useState<FrameworkOptions | null>(null);
  const [backendOptions, setBackendOptions] = useState<FrameworkOptions | null>(null);
  const [selectedFrameworks, setSelectedFrameworks] = useState<SelectedFrameworks | null>(null);
  const [pickerBackend, setPickerBackend] = useState("");
  const [pickerFrontend, setPickerFrontend] = useState("");

  const [showModuleModal, setShowModuleModal] = useState(false);
  const [moduleDescription, setModuleDescription] = useState("");
  const [isAddingModule, setIsAddingModule] = useState(false);

  const [isRunningTests, setIsRunningTests] = useState(false);
  const [runPhaseMessage, setRunPhaseMessage] = useState<string | null>(null);
  const [runResults, setRunResults] = useState<TestRunResults | null>(null);
  const [allTestsPassed, setAllTestsPassed] = useState(false);
  const [autoFixAttempts, setAutoFixAttempts] = useState(0);
  const [maxAttemptsReached, setMaxAttemptsReached] = useState(false);

  const cancelledRef = useRef(false);
  const autoFixAttemptsRef = useRef(0);

  useEffect(() => {
    cancelledRef.current = false;
    loadAll();
    return () => {
      cancelledRef.current = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const loadAll = async () => {
    try {
      const { data: fw } = await apiClient.get(`/testing/${projectId}/frameworks`);
      setFrontendOptions(fw.frontend);
      setBackendOptions(fw.backend);
      setPickerBackend(fw.selected?.backend || fw.backend.recommended);
      setPickerFrontend(fw.selected?.frontend || fw.frontend.recommended);
    } catch (error: any) {
      showToast(error.message || "Failed to load suitable testing frameworks.", "error");
      router.replace(`/(app)/project/${projectId}/codegen` as any);
      return;
    }

    try {
      const { data } = await apiClient.get(`/testing/${projectId}`);
      setTesting(data.testing);
      setSelectedFrameworks(data.selected_frameworks || null);
      setAutoFixAttempts(data.auto_fix_attempts || 0);
      autoFixAttemptsRef.current = data.auto_fix_attempts || 0;
      setRunResults(data.last_run_results || null);
      setAllTestsPassed(data.all_tests_passed || false);
      setMaxAttemptsReached(
        (data.auto_fix_attempts || 0) >= MAX_AUTO_FIX_ATTEMPTS &&
        !!data.last_run_results &&
        !data.all_tests_passed
      );
    } catch {
      // No tests yet — the framework picker pre-step handles this, not an error.
    } finally {
      setIsLoading(false);
    }
  };

  const generate = async (backendFramework: string, frontendFramework: string) => {
    setIsGenerating(true);
    try {
      const { data } = await apiClient.post("/testing/generate", {
        project_id: projectId,
        backend_framework: backendFramework,
        frontend_framework: frontendFramework,
      });
      setTesting(data.testing);
      setSelectedFile(null);
      setSelectedFrameworks({ backend: backendFramework, frontend: frontendFramework });
      setRunResults(null);
      setAllTestsPassed(false);
      setAutoFixAttempts(0);
      autoFixAttemptsRef.current = 0;
      setMaxAttemptsReached(false);
      showToast("Your test stubs are ready! 🧪🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to generate tests.", "error");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleSwitchFramework = (layer: "backend" | "frontend", value: string) => {
    if (isGenerating || isRunningTests || !selectedFrameworks || value === selectedFrameworks[layer]) return;
    const nextBackend = layer === "backend" ? value : selectedFrameworks.backend;
    const nextFrontend = layer === "frontend" ? value : selectedFrameworks.frontend;
    showToast("Regenerating tests for the new framework — your custom modules are kept.");
    generate(nextBackend, nextFrontend);
  };

  const handleAddModule = async () => {
    if (!moduleDescription.trim()) return;
    setIsAddingModule(true);
    try {
      const { data } = await apiClient.post("/testing/custom-module", {
        project_id: projectId,
        description: moduleDescription,
      });
      setTesting(data.testing);
      if (data.warnings?.length) {
        showToast(`Added, but Baby Tiger flagged: ${data.warnings[0]}`);
      } else {
        showToast(`Added ${data.added_files?.length || 0} custom test file(s)! 🧪🐯`);
      }
      setShowModuleModal(false);
      setModuleDescription("");
    } catch (error: any) {
      showToast(error.message || "Failed to add that test module.", "error");
    } finally {
      setIsAddingModule(false);
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

  const runTestsLoop = async () => {
    setMaxAttemptsReached(false);
    setIsRunningTests(true);
    setRunPhaseMessage("Baby Tiger is running your tests… 🧪🐯 this can take a few minutes");
    try {
      await apiClient.post("/testing/run", { project_id: projectId });

      let status = "queued";
      while (!cancelledRef.current && status !== "completed") {
        await sleep(POLL_INTERVAL_MS);
        const { data: statusData } = await apiClient.get(`/testing/${projectId}/run-status`);
        status = statusData.status;
      }
      if (cancelledRef.current) return;

      const { data: resultsData } = await apiClient.get(`/testing/${projectId}/run-results`);
      setRunResults(resultsData.results);
      setAllTestsPassed(resultsData.all_tests_passed);

      if (resultsData.all_tests_passed) {
        setIsRunningTests(false);
        setRunPhaseMessage(null);
        showToast(`All ${resultsData.results.total} tests passed! Moving to Export 🐯`);
        setTimeout(() => {
          handleApprove();
        }, 1500);
        return;
      }

      if (autoFixAttemptsRef.current < MAX_AUTO_FIX_ATTEMPTS) {
        setRunPhaseMessage(
          `Attempt ${autoFixAttemptsRef.current + 1}/${MAX_AUTO_FIX_ATTEMPTS}: Baby Tiger is fixing failing tests…`
        );
        const { data: fixData } = await apiClient.post("/testing/auto-fix", { project_id: projectId });
        autoFixAttemptsRef.current = fixData.attempts;
        setAutoFixAttempts(fixData.attempts);

        if (fixData.max_attempts_reached || !fixData.fixed_files?.length) {
          setIsRunningTests(false);
          setRunPhaseMessage(null);
          setMaxAttemptsReached(true);
          showToast(fixData.message);
          return;
        }

        showToast(fixData.message);
        await runTestsLoop();
        return;
      }

      setIsRunningTests(false);
      setRunPhaseMessage(null);
      setMaxAttemptsReached(true);
    } catch (error: any) {
      showToast(error.message || "Failed to run tests.", "error");
      setIsRunningTests(false);
      setRunPhaseMessage(null);
    }
  };

  if (isLoading || isGenerating) {
    return <PhaseLoading message={isGenerating ? "Baby Tiger is writing your tests... 🧪🐯" : "Loading..."} />;
  }

  // ── Framework picker pre-step — shown before any tests exist yet ──
  if (!testing) {
    return (
      <View style={[styles.screen, { backgroundColor: colors.background }]}>
        <PhaseHeader title="Testing" subtitle="Phase 5 of 7 — choose your testing setup" />
        <ScrollView style={styles.flex} contentContainerStyle={styles.pickerContent}>
          <Text style={{ color: colors.textSecondary, fontSize: 12, lineHeight: 17, marginBottom: 4 }}>
            Baby Tiger detected your tech stack and picked suitable testing frameworks below — change
            either one if you'd prefer something else.
          </Text>
          {backendOptions && (
            <FrameworkPickerRow
              label="Backend"
              detectedStack={backendOptions.detected_stack}
              options={backendOptions.options}
              value={pickerBackend}
              onChange={setPickerBackend}
              colors={colors}
            />
          )}
          {frontendOptions && (
            <FrameworkPickerRow
              label="Frontend"
              detectedStack={frontendOptions.detected_stack}
              options={frontendOptions.options}
              value={pickerFrontend}
              onChange={setPickerFrontend}
              colors={colors}
            />
          )}
        </ScrollView>
        <PhaseFooter
          note="Baby Tiger will write test stubs in these frameworks' style."
          primaryLabel="Generate Tests"
          primaryIcon={FlaskConical}
          onPrimaryPress={() => generate(pickerBackend, pickerFrontend)}
        />
      </View>
    );
  }

  const hasRunResults = runResults !== null;
  const showFailuresBlocked =
    hasRunResults && !allTestsPassed && !isRunningTests && (maxAttemptsReached || autoFixAttempts >= MAX_AUTO_FIX_ATTEMPTS);

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <PhaseHeader
        title="Testing"
        subtitle={`Phase 5 of 7 — ${testing.test_files.length} test file${testing.test_files.length === 1 ? "" : "s"} generated`}
      />

      <Pressable
        onPress={() => setShowModuleModal(true)}
        style={[styles.addModuleRow, { borderColor: colors.border }]}
      >
        <Plus size={14} color={colors.textPrimary} />
        <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "600" }}>Add Testing Module</Text>
      </Pressable>

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

      {selectedFrameworks && backendOptions && frontendOptions && (
        <View style={[styles.frameworkSection, { borderBottomColor: colors.border }]}>
          <FrameworkPillRow
            label="Backend"
            options={backendOptions.options}
            selected={selectedFrameworks.backend}
            disabled={isGenerating || isRunningTests}
            onSelect={(v) => handleSwitchFramework("backend", v)}
            colors={colors}
          />
          <FrameworkPillRow
            label="Frontend"
            options={frontendOptions.options}
            selected={selectedFrameworks.frontend}
            disabled={isGenerating || isRunningTests}
            onSelect={(v) => handleSwitchFramework("frontend", v)}
            colors={colors}
          />
        </View>
      )}

      <View style={[styles.runSection, { borderBottomColor: colors.border }]}>
        {isRunningTests ? (
          <View style={styles.runRow}>
            <ActivityIndicator size="small" color={colors.primary} />
            <Text style={{ color: colors.textSecondary, fontSize: 12, flex: 1 }}>{runPhaseMessage}</Text>
          </View>
        ) : hasRunResults && allTestsPassed ? (
          <View style={styles.runRow}>
            <CheckCircle2 size={16} color={colors.success} />
            <Text style={{ color: colors.success, fontSize: 12, fontWeight: "600" }}>
              All {runResults?.total} tests passed — moving to Export…
            </Text>
          </View>
        ) : showFailuresBlocked ? (
          <View style={{ gap: 8 }}>
            <View style={styles.runRow}>
              <XCircle size={16} color={colors.error} />
              <Text style={{ color: colors.error, fontSize: 12, fontWeight: "600", flex: 1 }}>
                {runResults?.failed} of {runResults?.total} tests still failing — Baby Tiger tried{" "}
                {autoFixAttempts} automatic fix{autoFixAttempts === 1 ? "" : "es"} and couldn't resolve everything.
              </Text>
            </View>
            {runResults?.failures.slice(0, 5).map((f, i) => (
              <Text key={i} style={[styles.mono, { color: colors.textTertiary, fontSize: 10 }]} numberOfLines={1}>
                {f.file} — {f.test_name}: {f.message}
              </Text>
            ))}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 4 }}>
              <Pressable
                onPress={runTestsLoop}
                style={[styles.smallButton, { borderColor: colors.border }]}
              >
                <RotateCcw size={13} color={colors.textPrimary} />
                <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "600" }}>Try Again</Text>
              </Pressable>
              <Pressable onPress={handleApprove} disabled={isApproving} style={styles.smallButton}>
                <Text style={{ color: colors.textSecondary, fontSize: 12, fontWeight: "600" }}>Continue Anyway</Text>
              </Pressable>
            </View>
          </View>
        ) : (
          <View style={styles.runRow}>
            <Text style={{ color: colors.textTertiary, fontSize: 12, flex: 1 }}>
              {hasRunResults
                ? `Last run: ${runResults?.passed} passed, ${runResults?.failed} failed`
                : "Run the tests for real — Baby Tiger will try to fix any failures automatically."}
            </Text>
            <Pressable
              onPress={runTestsLoop}
              style={[styles.runButton, { backgroundColor: colors.primary }]}
            >
              <Play size={13} color="#fff" />
              <Text style={{ color: "#fff", fontSize: 12, fontWeight: "700" }}>Run Tests</Text>
            </Pressable>
          </View>
        )}
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
              {selectedFile.framework && (
                <Text style={{ color: colors.textTertiary, fontSize: 11 }}> · {selectedFile.framework}</Text>
              )}
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
              {file.source === "custom" && (
                <View style={[styles.customBadge, { backgroundColor: colors.primaryLight }]}>
                  <Text style={{ color: colors.primary, fontSize: 9, fontWeight: "700" }}>Custom</Text>
                </View>
              )}
            </Pressable>
          ))}
        </ScrollView>
      )}

      <PhaseFooter
        note="Run the tests above for real results, or approve manually to continue to Export 📦"
        secondaryActions={[{ label: "Export Docs", icon: BookOpen, onPress: handleDownloadDocs, loading: isDownloadingDocs }]}
        primaryLabel="Approve & Continue"
        primaryIcon={ThumbsUp}
        onPrimaryPress={handleApprove}
        primaryLoading={isApproving}
      />

      <Modal visible={showModuleModal} transparent animationType="fade" onRequestClose={() => setShowModuleModal(false)}>
        <View style={styles.modalOverlay}>
          <View style={[styles.modalCard, { backgroundColor: colors.surface }]}>
            <View style={styles.modalHeader}>
              <Text style={{ color: colors.textPrimary, fontSize: 14, fontWeight: "700" }}>
                What should Baby Tiger test?
              </Text>
              <Pressable onPress={() => setShowModuleModal(false)} hitSlop={8}>
                <X size={18} color={colors.textSecondary} />
              </Pressable>
            </View>
            <TextInput
              value={moduleDescription}
              onChangeText={setModuleDescription}
              placeholder="e.g. Test that a user can't check out with an empty cart"
              placeholderTextColor={colors.textTertiary}
              multiline
              numberOfLines={6}
              style={[
                styles.modalTextArea,
                { borderColor: colors.border, color: colors.textPrimary, backgroundColor: colors.background },
              ]}
            />
            <Pressable
              onPress={handleAddModule}
              disabled={isAddingModule || !moduleDescription.trim()}
              style={[styles.modalSubmit, { backgroundColor: colors.primary }, (isAddingModule || !moduleDescription.trim()) && { opacity: 0.6 }]}
            >
              {isAddingModule ? <ActivityIndicator size="small" color="#fff" /> : <Wrench size={15} color="#fff" />}
              <Text style={{ color: "#fff", fontWeight: "700", fontSize: 13 }}>Generate Test Module</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function FrameworkPickerRow({
  label,
  detectedStack,
  options,
  value,
  onChange,
  colors,
}: {
  label: string;
  detectedStack: string;
  options: string[];
  value: string;
  onChange: (v: string) => void;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={[styles.pickerCard, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "700" }}>{label}</Text>
      {!!detectedStack && (
        <Text style={{ color: colors.textTertiary, fontSize: 11, marginBottom: 6 }}>Detected: {detectedStack}</Text>
      )}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {options.map((opt) => (
          <Pressable
            key={opt}
            onPress={() => onChange(opt)}
            style={[
              styles.pill,
              { borderColor: value === opt ? colors.primary : colors.border },
              value === opt && { backgroundColor: colors.primaryLight },
            ]}
          >
            <Text style={{ color: value === opt ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>
              {opt}
            </Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

function FrameworkPillRow({
  label,
  options,
  selected,
  disabled,
  onSelect,
  colors,
}: {
  label: string;
  options: string[];
  selected: string;
  disabled: boolean;
  onSelect: (v: string) => void;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
      <Text style={{ color: colors.textTertiary, fontSize: 11, fontWeight: "700", width: 64 }}>{label}</Text>
      {options.map((opt) => (
        <Pressable
          key={opt}
          onPress={() => onSelect(opt)}
          disabled={disabled}
          style={[
            styles.smallPill,
            { borderColor: opt === selected ? colors.primary : colors.border },
            opt === selected && { backgroundColor: colors.primaryLight },
            disabled && { opacity: 0.6 },
          ]}
        >
          <Text style={{ color: opt === selected ? colors.primary : colors.textSecondary, fontSize: 11, fontWeight: "600" }}>
            {opt}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  flex: { flex: 1 },
  summaryBanner: { padding: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  warningBanner: { flexDirection: "row", gap: 8, padding: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  addModuleRow: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    marginHorizontal: 16, marginTop: 10, paddingHorizontal: 12, paddingVertical: 7,
    borderWidth: 1, borderRadius: 10,
  },
  frameworkSection: { padding: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  runSection: { padding: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  runRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  runButton: { flexDirection: "row", alignItems: "center", gap: 6, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 9 },
  smallButton: { flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 7 },
  fileListContent: { padding: 12 },
  fileRow: { flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderRadius: 10, padding: 12, marginBottom: 8 },
  customBadge: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 6 },
  backToFilesRow: { flexDirection: "row", alignItems: "center", gap: 6, padding: 12 },
  fileMetaBox: { paddingHorizontal: 12, paddingBottom: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  testsWhatRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6, flexWrap: "wrap" },
  mono: { fontFamily: "monospace" },
  codeScroll: { padding: 12 },
  code: { fontSize: 11, lineHeight: 16, padding: 12, borderRadius: 10 },
  pickerContent: { padding: 16, gap: 12 },
  pickerCard: { borderWidth: 1, borderRadius: 12, padding: 12 },
  pill: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 7 },
  smallPill: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", alignItems: "center", justifyContent: "center", padding: 24 },
  modalCard: { width: "100%", maxWidth: 480, borderRadius: 16, padding: 16 },
  modalHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  modalTextArea: { borderWidth: 1, borderRadius: 10, padding: 10, fontSize: 12, minHeight: 120, textAlignVertical: "top" },
  modalSubmit: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, borderRadius: 12, paddingVertical: 12, marginTop: 12 },
});
