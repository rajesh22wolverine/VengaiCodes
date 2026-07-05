import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft, FileCode2, ChevronRight, Loader2, ThumbsUp,
  FolderTree, AlertTriangle, Target
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

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
  python: "var(--color-info)",
  typescript: "var(--color-primary)",
  javascript: "var(--color-warning)",
  tsx: "var(--color-primary)",
  jsx: "var(--color-warning)",
};

export default function TestingScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [testing, setTesting] = useState<TestPlanResult | null>(null);
  const [selectedFile, setSelectedFile] = useState<GeneratedTestFile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/testing/${projectId}`);
      setTesting(data.testing);
      setSelectedFile(data.testing.test_files?.[0] || null);
      setIsLoading(false);
    } catch {
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/testing/generate", {
        project_id: projectId,
      });
      setTesting(data.testing);
      setSelectedFile(data.testing.test_files?.[0] || null);
      toast.success("Your test stubs are ready! 🧪🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to generate tests.");
      navigate(`/project/${projectId}/codegen`);
    } finally {
      setIsGenerating(false);
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

  if (isLoading || isGenerating) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 bg-[var(--color-background)]">
        <BabyTiger size={100} expression="thinking" />
        <p className="text-[var(--color-text-secondary)] text-sm">
          {isGenerating
            ? "Baby Tiger is writing your tests... 🧪🐯"
            : "Loading..."}
        </p>
      </div>
    );
  }

  if (!testing) return null;

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
                  className={`text-xs font-mono truncate ${
                    selectedFile?.path === file.path
                      ? "text-[var(--color-primary)] font-medium"
                      : "text-[var(--color-text-secondary)]"
                  }`}
                >
                  {file.path.split("/").pop()}
                </span>
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
                <div className="flex items-center gap-1.5">
                  <Target className="w-3 h-3 text-[var(--color-text-tertiary)]" />
                  <span className="text-xs text-[var(--color-text-tertiary)] font-mono">
                    Tests: {selectedFile.tests_what}
                  </span>
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
            These are test stubs, not verified passing tests — review, then continue to Export 📦
          </p>
          <button
            onClick={handleApprove}
            disabled={isApproving}
            className="px-6 py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center gap-2 flex-shrink-0"
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
  );
}