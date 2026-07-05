import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft, Download, Loader2, PartyPopper, FileText,
  Code2, TestTube2, Palette, Layers, CheckCircle2
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

interface ProjectSummary {
  name: string;
  files_generated: number;
  tests_generated: number;
}

export default function ExportScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);

  useEffect(() => {
    loadSummary();
  }, [projectId]);

  const loadSummary = async () => {
    try {
      const { data } = await apiClient.get(`/projects/${projectId}`);
      setSummary({
        name: data.project.name,
        files_generated: data.project.codegen_data?.codegen?.files?.length || 0,
        tests_generated: data.project.testing_data?.testing?.test_files?.length || 0,
      });
    } catch (error: any) {
      toast.error("Failed to load project summary.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownload = async () => {
    setIsDownloading(true);
    try {
      const response = await apiClient.get(`/export/${projectId}/download`, {
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "vengaicode_export.zip");
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Downloaded! Check your Downloads folder 🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to download files.");
    } finally {
      setIsDownloading(false);
    }
  };

  const handleFinish = () => {
    toast.success("Nice work! Your project is saved in Completed 🐯", { duration: 4000 });
    navigate("/home");
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 bg-[var(--color-background)]">
        <BabyTiger size={100} expression="thinking" />
        <p className="text-[var(--color-text-secondary)] text-sm">Loading...</p>
      </div>
    );
  }

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
        <BabyTiger size={36} expression="celebrating" />
        <div className="flex-1">
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">
            Export
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Phase 6 of 7 — Your project is ready to download
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-10">
        <div className="max-w-2xl mx-auto">
          {/* Celebration header */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-center mb-8"
          >
            <div className="flex justify-center mb-4">
              <BabyTiger size={120} expression="celebrating" />
            </div>
            <h2 className="text-2xl font-bold text-[var(--color-text-primary)] mb-2">
              {summary?.name || "Your project"} is ready! 🎉
            </h2>
            <p className="text-[var(--color-text-secondary)] text-sm">
              Baby Tiger built your requirements, design, architecture, code, and tests.
              Download everything below.
            </p>
          </motion.div>

          {/* Journey recap */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 mb-6"
          >
            <h3 className="text-sm font-semibold text-[var(--color-text-primary)] mb-4">
              What was built
            </h3>
            <div className="space-y-3">
              <JourneyItem icon={FileText} label="Requirements Document" done />
              <JourneyItem icon={Palette} label="UI/UX Design System" done />
              <JourneyItem icon={Layers} label="Technical Architecture" done />
              <JourneyItem
                icon={Code2}
                label={`Starter Code (${summary?.files_generated || 0} files)`}
                done
              />
              <JourneyItem
                icon={TestTube2}
                label={`Test Stubs (${summary?.tests_generated || 0} files)`}
                done
              />
            </div>
          </motion.div>

          {/* Honest scope notice */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="rounded-2xl border border-[var(--color-warning)] bg-[var(--color-warning-light)] p-4 mb-6"
          >
            <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
              <span className="font-semibold text-[var(--color-text-primary)]">Good to know: </span>
              This download includes a starter code skeleton and test stubs — not a
              finished, runnable application yet. Packaged installers (.exe/.msi/.apk)
              are coming in a future update. For now, use the generated files as a
              well-organized starting point.
            </p>
          </motion.div>

          {/* Download */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="flex flex-col sm:flex-row gap-3"
          >
            <button
              onClick={handleDownload}
              disabled={isDownloading}
              className="flex-1 py-4 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center justify-center gap-2 shadow-md hover:shadow-lg"
            >
              {isDownloading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Download className="w-4 h-4" />
              )}
              Download Project ZIP
            </button>
            <button
              onClick={handleFinish}
              className="flex-1 py-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-primary)] font-semibold text-sm hover:bg-[var(--color-surface-raised)] transition-colors flex items-center justify-center gap-2"
            >
              <PartyPopper className="w-4 h-4" />
              Finish & Return Home
            </button>
          </motion.div>
        </div>
      </div>
    </div>
  );
}

function JourneyItem({
  icon: Icon,
  label,
  done,
}: {
  icon: React.ElementType;
  label: string;
  done: boolean;
}) {
  return (
    <div className="flex items-center gap-3">
      <div
        className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
          done ? "bg-[var(--color-success-light)]" : "bg-[var(--color-surface-raised)]"
        }`}
      >
        <Icon
          className="w-4 h-4"
          style={{ color: done ? "var(--color-success)" : "var(--color-text-tertiary)" }}
        />
      </div>
      <span className="text-sm text-[var(--color-text-primary)] flex-1">{label}</span>
      {done && <CheckCircle2 className="w-4 h-4 text-[var(--color-success)] flex-shrink-0" />}
    </div>
  );
}