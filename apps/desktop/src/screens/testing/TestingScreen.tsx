import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, FileCode2, ChevronRight, Loader2, ThumbsUp,
  FolderTree, AlertTriangle, Target, BookOpen, Play, Plus, X,
  CheckCircle2, XCircle, RotateCcw, Wrench, FlaskConical,
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import ChatPanel from "@/components/chat/ChatPanel";

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
  python: "var(--color-info)",
  typescript: "var(--color-primary)",
  javascript: "var(--color-warning)",
  tsx: "var(--color-primary)",
  jsx: "var(--color-warning)",
};

const MAX_AUTO_FIX_ATTEMPTS = 3;
const POLL_INTERVAL_MS = 8000;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export default function TestingScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [testing, setTesting] = useState<TestPlanResult | null>(null);
  const [selectedFile, setSelectedFile] = useState<GeneratedTestFile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  // Framework selection
  const [frontendOptions, setFrontendOptions] = useState<FrameworkOptions | null>(null);
  const [backendOptions, setBackendOptions] = useState<FrameworkOptions | null>(null);
  const [selectedFrameworks, setSelectedFrameworks] = useState<SelectedFrameworks | null>(null);
  const [pickerBackend, setPickerBackend] = useState<string>("");
  const [pickerFrontend, setPickerFrontend] = useState<string>("");

  // "+ Add Testing Module"
  const [showModuleModal, setShowModuleModal] = useState(false);
  const [moduleDescription, setModuleDescription] = useState("");
  const [isAddingModule, setIsAddingModule] = useState(false);

  // Real test run + bounded auto-fix loop
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
      toast.error(error.message || "Failed to load suitable testing frameworks.");
      navigate(`/project/${projectId}/codegen`);
      return;
    }

    try {
      const { data } = await apiClient.get(`/testing/${projectId}`);
      setTesting(data.testing);
      setSelectedFile(data.testing.test_files?.[0] || null);
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
      setSelectedFile(data.testing.test_files?.[0] || null);
      setSelectedFrameworks({ backend: backendFramework, frontend: frontendFramework });
      setRunResults(null);
      setAllTestsPassed(false);
      setAutoFixAttempts(0);
      autoFixAttemptsRef.current = 0;
      setMaxAttemptsReached(false);
      toast.success("Your test stubs are ready! 🧪🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to generate tests.");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleSwitchFramework = (layer: "backend" | "frontend", value: string) => {
    if (isGenerating || isRunningTests || !selectedFrameworks || value === selectedFrameworks[layer]) return;
    const nextBackend = layer === "backend" ? value : selectedFrameworks.backend;
    const nextFrontend = layer === "frontend" ? value : selectedFrameworks.frontend;
    toast("Regenerating tests for the new framework — your custom modules are kept.", { icon: "🔄" });
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
      if (data.added_files?.[0]) setSelectedFile(data.added_files[0]);
      if (data.warnings?.length) {
        toast(`Added, but Baby Tiger flagged: ${data.warnings[0]}`, { icon: "⚠️" });
      } else {
        toast.success(`Added ${data.added_files?.length || 0} custom test file(s)! 🧪🐯`);
      }
      setShowModuleModal(false);
      setModuleDescription("");
    } catch (error: any) {
      toast.error(error.message || "Failed to add that test module.");
    } finally {
      setIsAddingModule(false);
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
      await apiClient.post("/testing/approve", {
        project_id: projectId,
        approved: true,
      });
      toast.success("Tests approved! Next: Export 🐯");
      navigate(`/project/${projectId}/export`);
    } catch (error: any) {
      toast.error(error.message || "Failed to approve.");
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
        toast.success(`All ${resultsData.results.total} tests passed! Moving to Export 🐯`);
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
          toast(fixData.message, { icon: "🐯" });
          return;
        }

        toast(fixData.message, { icon: "🛠️" });
        await runTestsLoop();
        return;
      }

      setIsRunningTests(false);
      setRunPhaseMessage(null);
      setMaxAttemptsReached(true);
    } catch (error: any) {
      toast.error(error.message || "Failed to run tests.");
      setIsRunningTests(false);
      setRunPhaseMessage(null);
    }
  };

  if (isLoading || isGenerating) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 bg-[var(--color-background)]">
        <BabyTiger size={100} expression="thinking" />
        <p className="text-[var(--color-text-secondary)] text-sm">
          {isGenerating
            ? "Baby Tiger is writing your tests… 🧪🐯"
            : "Loading..."}
        </p>
      </div>
    );
  }

  // ── Framework picker pre-step — shown before any tests exist yet ──
  if (!testing) {
    return (
      <div className="flex-1 flex flex-col h-full bg-[var(--color-background)] overflow-hidden">
        <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
          <button
            onClick={() => navigate("/home")}
            className="p-2 rounded-lg hover:bg-[var(--color-surface-raised)] transition-colors"
          >
            <ArrowLeft className="w-4 h-4 text-[var(--color-text-secondary)]" />
          </button>
          <BabyTiger size={36} expression="idle" />
          <div className="flex-1">
            <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">Testing</h1>
            <p className="text-xs text-[var(--color-text-tertiary)]">Phase 5 of 7 — choose your testing setup</p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          <div className="max-w-2xl mx-auto space-y-6">
            <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
              Baby Tiger detected your tech stack and picked suitable testing frameworks below —
              change either one if you'd prefer something else.
            </p>

            {backendOptions && (
              <FrameworkPickerRow
                label="Backend"
                detectedStack={backendOptions.detected_stack}
                options={backendOptions.options}
                value={pickerBackend}
                onChange={setPickerBackend}
              />
            )}
            {frontendOptions && (
              <FrameworkPickerRow
                label="Frontend"
                detectedStack={frontendOptions.detected_stack}
                options={frontendOptions.options}
                value={pickerFrontend}
                onChange={setPickerFrontend}
              />
            )}

            <button
              onClick={() => generate(pickerBackend, pickerFrontend)}
              className="w-full py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors flex items-center justify-center gap-2"
            >
              <FlaskConical className="w-4 h-4" />
              Generate Tests
            </button>
          </div>
        </div>
      </div>
    );
  }

  const hasRunResults = runResults !== null;
  const showFailuresBlocked = hasRunResults && !allTestsPassed && !isRunningTests && (maxAttemptsReached || autoFixAttempts >= MAX_AUTO_FIX_ATTEMPTS);

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
            Testing
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Phase 5 of 7 — {testing.test_files.length} test file{testing.test_files.length === 1 ? "" : "s"} generated
          </p>
        </div>
        <button
          onClick={() => setShowModuleModal(true)}
          className="px-3 py-2 rounded-lg border border-[var(--color-border)] text-[var(--color-text-primary)] text-xs font-semibold hover:bg-[var(--color-surface-raised)] transition-colors flex items-center gap-1.5"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Testing Module
        </button>
      </div>

      {/* Summary banner */}
      <div className="px-6 py-3 bg-[var(--color-primary-light)] border-b border-[var(--color-border)] flex-shrink-0">
        <p className="text-xs text-[var(--color-primary)] leading-relaxed max-w-3xl">
          {testing.summary}
        </p>
      </div>

      {/* Coverage notes — honest disclaimer, always visible */}
      <div className="px-6 py-3 bg-[var(--color-warning-light)] border-b border-[var(--color-border)] flex-shrink-0">
        <div className="flex items-start gap-2 max-w-3xl">
          <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-warning)] flex-shrink-0 mt-0.5" />
          <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
            <span className="font-semibold text-[var(--color-text-primary)]">Coverage notes: </span>
            {testing.coverage_notes}
          </p>
        </div>
      </div>

      {/* Framework row */}
      {selectedFrameworks && backendOptions && frontendOptions && (
        <div className="px-6 py-3 border-b border-[var(--color-border)] flex-shrink-0 space-y-2">
          <FrameworkPillRow
            label="Backend"
            options={backendOptions.options}
            selected={selectedFrameworks.backend}
            disabled={isGenerating || isRunningTests}
            onSelect={(v) => handleSwitchFramework("backend", v)}
          />
          <FrameworkPillRow
            label="Frontend"
            options={frontendOptions.options}
            selected={selectedFrameworks.frontend}
            disabled={isGenerating || isRunningTests}
            onSelect={(v) => handleSwitchFramework("frontend", v)}
          />
        </div>
      )}

      {/* Run tests + results */}
      <div className="px-6 py-3 border-b border-[var(--color-border)] flex-shrink-0">
        {isRunningTests ? (
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
            <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--color-primary)]" />
            {runPhaseMessage}
          </div>
        ) : hasRunResults && allTestsPassed ? (
          <div className="flex items-center gap-2 text-xs text-[var(--color-success)] font-medium">
            <CheckCircle2 className="w-4 h-4" />
            All {runResults?.total} tests passed — moving to Export…
          </div>
        ) : showFailuresBlocked ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-[var(--color-error)] font-medium">
              <XCircle className="w-4 h-4" />
              {runResults?.failed} of {runResults?.total} tests still failing — Baby Tiger tried {autoFixAttempts} automatic fix{autoFixAttempts === 1 ? "" : "es"} and couldn't resolve everything.
            </div>
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {runResults?.failures.map((f, i) => (
                <p key={i} className="text-xs text-[var(--color-text-tertiary)] font-mono truncate">
                  {f.file} — {f.test_name}: {f.message}
                </p>
              ))}
            </div>
            <div className="flex items-center gap-2 pt-1">
              <button
                onClick={runTestsLoop}
                className="px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-[var(--color-text-primary)] text-xs font-semibold hover:bg-[var(--color-surface-raised)] transition-colors flex items-center gap-1.5"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                Try Again
              </button>
              <button
                onClick={handleApprove}
                disabled={isApproving}
                className="px-3 py-1.5 rounded-lg text-[var(--color-text-secondary)] text-xs font-medium hover:bg-[var(--color-surface-raised)] transition-colors disabled:opacity-60"
              >
                Continue Anyway
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-[var(--color-text-tertiary)]">
              {hasRunResults
                ? `Last run: ${runResults?.passed} passed, ${runResults?.failed} failed`
                : "Run the tests for real — Baby Tiger will try to fix any failures automatically."}
            </p>
            <button
              onClick={runTestsLoop}
              className="px-4 py-2 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors flex items-center gap-1.5"
            >
              <Play className="w-3.5 h-3.5" />
              Run Tests
            </button>
          </div>
        )}
      </div>

      {/* Main content — file tree + code preview */}
      <div className="flex-1 flex overflow-hidden">
        {/* File tree sidebar */}
        <div className="w-64 flex-shrink-0 border-r border-[var(--color-border)] bg-[var(--color-surface)] overflow-y-auto">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--color-border)]">
            <FolderTree className="w-3.5 h-3.5 text-[var(--color-text-tertiary)]" />
            <span className="text-xs font-semibold text-[var(--color-text-tertiary)] uppercase tracking-wider">
              Test Files
            </span>
          </div>
          <div className="py-2">
            {testing.test_files.map((file, i) => (
              <button
                key={i}
                onClick={() => setSelectedFile(file)}
                className={`w-full flex items-center gap-2 px-4 py-2.5 text-left transition-colors ${
                  selectedFile?.path === file.path
                    ? "bg-[var(--color-primary-light)] border-r-2 border-[var(--color-primary)]"
                    : "hover:bg-[var(--color-surface-raised)]"
                }`}
              >
                <FileCode2
                  className="w-3.5 h-3.5 flex-shrink-0"
                  style={{ color: LANGUAGE_COLORS[file.language] || "var(--color-text-tertiary)" }}
                />
                <span
                  className={`text-xs font-mono truncate flex-1 ${
                    selectedFile?.path === file.path
                      ? "text-[var(--color-primary)] font-medium"
                      : "text-[var(--color-text-secondary)]"
                  }`}
                >
                  {file.path.split("/").pop()}
                </span>
                {file.source === "custom" && (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-[var(--color-primary-light)] text-[var(--color-primary)] font-semibold flex-shrink-0">
                    Custom
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Code preview */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {selectedFile ? (
            <>
              <div className="px-6 py-3 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
                <div className="flex items-center gap-2 text-xs text-[var(--color-text-tertiary)] font-mono mb-1">
                  {selectedFile.path.split("/").map((part, i, arr) => (
                    <span key={i} className="flex items-center gap-2">
                      {part}
                      {i < arr.length - 1 && <ChevronRight className="w-3 h-3" />}
                    </span>
                  ))}
                </div>
                <p className="text-xs text-[var(--color-text-secondary)] mb-1">
                  {selectedFile.description}
                </p>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1.5">
                    <Target className="w-3 h-3 text-[var(--color-text-tertiary)]" />
                    <span className="text-xs text-[var(--color-text-tertiary)] font-mono">
                      Tests: {selectedFile.tests_what}
                    </span>
                  </div>
                  {selectedFile.framework && (
                    <span className="text-xs text-[var(--color-text-tertiary)]">
                      · {selectedFile.framework}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-auto p-6">
                <motion.pre
                  key={selectedFile.path}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="text-xs font-mono text-[var(--color-text-primary)] bg-[var(--color-surface-raised)] rounded-xl p-4 leading-relaxed whitespace-pre-wrap"
                >
                  <code>{selectedFile.content}</code>
                </motion.pre>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-[var(--color-text-tertiary)]">
              Select a file to preview
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="flex-shrink-0 px-6 py-4 border-t border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Run the tests above for real results, or approve manually to continue to Export 📦
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

      {/* Add Testing Module modal */}
      <AnimatePresence>
        {showModuleModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6"
          >
            <div className="bg-[var(--color-surface)] rounded-2xl p-4 max-w-lg w-full">
              <div className="flex items-center justify-between mb-3">
                <p className="text-sm font-semibold text-[var(--color-text-primary)]">
                  What should Baby Tiger test?
                </p>
                <button
                  onClick={() => setShowModuleModal(false)}
                  className="p-1.5 rounded-lg hover:bg-[var(--color-surface-raised)] transition-colors"
                >
                  <X className="w-4 h-4 text-[var(--color-text-secondary)]" />
                </button>
              </div>

              <textarea
                value={moduleDescription}
                onChange={(e) => setModuleDescription(e.target.value)}
                placeholder="e.g. Test that a user can't check out with an empty cart, and that the total updates when quantity changes"
                className="w-full h-40 rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-xs font-mono text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)] resize-y"
              />

              <button
                onClick={handleAddModule}
                disabled={isAddingModule || !moduleDescription.trim()}
                className="mt-3 w-full py-2.5 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
              >
                {isAddingModule ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Wrench className="w-4 h-4" />
                )}
                Generate Test Module
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <ChatPanel projectId={projectId} phase="testing" />
    </div>
  );
}

function FrameworkPickerRow({
  label,
  detectedStack,
  options,
  value,
  onChange,
}: {
  label: string;
  detectedStack: string;
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 space-y-2">
      <div>
        <p className="text-xs font-semibold text-[var(--color-text-primary)]">{label}</p>
        {detectedStack && (
          <p className="text-xs text-[var(--color-text-tertiary)]">Detected: {detectedStack}</p>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => (
          <button
            key={opt}
            onClick={() => onChange(opt)}
            className={`px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors ${
              value === opt
                ? "border-[var(--color-primary)] text-[var(--color-primary)] bg-[var(--color-primary-light)]"
                : "border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)]"
            }`}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  );
}

function FrameworkPillRow({
  label,
  options,
  selected,
  disabled,
  onSelect,
}: {
  label: string;
  options: string[];
  selected: string;
  disabled: boolean;
  onSelect: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs font-semibold text-[var(--color-text-tertiary)] w-16 flex-shrink-0">{label}</span>
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => onSelect(opt)}
          disabled={disabled}
          title={opt === selected ? "Currently used" : `Switch to ${opt}`}
          className={`px-2.5 py-1 rounded-full border text-xs font-medium transition-colors disabled:opacity-60 ${
            opt === selected
              ? "border-[var(--color-primary)] text-[var(--color-primary)] bg-[var(--color-primary-light)]"
              : "border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)]"
          }`}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}
