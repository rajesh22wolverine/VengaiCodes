import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft, FileCode2, ChevronRight, Loader2, ThumbsUp, FolderTree
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

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

const LANGUAGE_COLORS: Record<string, string> = {
  python: "var(--color-info)",
  typescript: "var(--color-primary)",
  javascript: "var(--color-warning)",
  tsx: "var(--color-primary)",
  jsx: "var(--color-warning)",
  json: "var(--color-text-tertiary)",
};

export default function CodeGenScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [codegen, setCodegen] = useState<CodeGenResult | null>(null);
  const [selectedFile, setSelectedFile] = useState<GeneratedFile | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/codegen/${projectId}`);
      setCodegen(data.codegen);
      setSelectedFile(data.codegen.files?.[0] || null);
      setIsLoading(false);
    } catch {
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/codegen/generate", {
        project_id: projectId,
      });
      setCodegen(data.codegen);
      setSelectedFile(data.codegen.files?.[0] || null);
      toast.success("Your code is ready! 💻🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to generate code.");
      navigate(`/project/${projectId}/architecture`);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleApprove = async () => {
    setIsApproving(true);
    try {
      await apiClient.post("/codegen/approve", {
        project_id: projectId,
        approved: true,
      });
      toast.success("Code approved! Next: Testing 🐯");
      navigate(`/project/${projectId}/testing`);
    } catch (error: any) {
      toast.error(error.message || "Failed to approve.");
    } finally {
      setIsApproving(false);
    }
  };

  if (isLoading || isGenerating) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 bg-[var(--color-background)]">
        <BabyTiger size={100} expression="coding" />
        <p className="text-[var(--color-text-secondary)] text-sm">
          {isGenerating
            ? "Baby Tiger is writing your code... 💻🐯"
            : "Loading..."}
        </p>
      </div>
    );
  }

  if (!codegen) return null;

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
            Code Generation
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Phase 4 of 7 — {codegen.files.length} file{codegen.files.length === 1 ? "" : "s"} generated
          </p>
        </div>
      </div>

      {/* Summary banner */}
      <div className="px-6 py-3 bg-[var(--color-primary-light)] border-b border-[var(--color-border)] flex-shrink-0">
        <p className="text-xs text-[var(--color-primary)] leading-relaxed max-w-3xl">
          {codegen.summary}
        </p>
      </div>

      {/* Main content — file tree + code preview */}
      <div className="flex-1 flex overflow-hidden">
        {/* File tree sidebar */}
        <div className="w-64 flex-shrink-0 border-r border-[var(--color-border)] bg-[var(--color-surface)] overflow-y-auto">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-[var(--color-border)]">
            <FolderTree className="w-3.5 h-3.5 text-[var(--color-text-tertiary)]" />
            <span className="text-xs font-semibold text-[var(--color-text-tertiary)] uppercase tracking-wider">
              Files
            </span>
          </div>
          <div className="py-2">
            {codegen.files.map((file, i) => (
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
                <p className="text-xs text-[var(--color-text-secondary)]">
                  {selectedFile.description}
                </p>
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
            This is a starter skeleton — review the structure, then continue to Testing 🧪
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
