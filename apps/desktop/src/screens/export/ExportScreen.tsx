import { useEffect, useState, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Download, Loader2, PartyPopper, FileText,
  Code2, TestTube2, Palette, Layers, CheckCircle2, Package,
  AlertCircle, ExternalLink, Monitor
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

type BuildStatus = "idle" | "queued" | "in_progress" | "completed" | "failed";

interface ProjectSummary {
  name: string;
  files_generated: number;
  tests_generated: number;
}

interface BuildArtifact {
  name: string;
  size_bytes: number;
  id: number;
}

// Poll every 15 seconds — builds take minutes, no need to hammer the API
const POLL_INTERVAL_MS = 15000;
// Stop polling after 25 minutes even if GitHub Actions hasn't finished —
// avoids an infinite spinner if something goes wrong
const POLL_TIMEOUT_MS = 25 * 60 * 1000;

export default function ExportScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [summary, setSummary] = useState<ProjectSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDownloading, setIsDownloading] = useState(false);

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

  const handleFinish = async () => {
  try {
    await apiClient.post(`/projects/${projectId}/complete`);
    toast.success("Nice work! Your project is saved in Completed 🐯", { duration: 4000 });
    navigate("/home");
  } catch (error: any) {
    // Non-blocking — if this fails the user still gets home, we just log it
    console.error("Failed to mark complete:", error);
    toast.success("Returning home 🐯");
    navigate("/home");
  }
};

  // ── Windows installer build ──

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
          toast.success("Your installer is ready! 🐯🎉");
          fetchArtifacts();
        } else {
          setBuildStatus("failed");
          toast.error("Build failed. Check the build log for details.");
        }
        return;
      }

      setBuildStatus(data.status === "queued" ? "queued" : "in_progress");

      // Safety timeout — stop polling if it's been running too long
      if (
        pollStartedAtRef.current &&
        Date.now() - pollStartedAtRef.current > POLL_TIMEOUT_MS
      ) {
        stopPolling();
        toast.error("Build is taking longer than expected. Check the log directly.");
      }
    } catch (error: any) {
      // Don't stop polling on a single failed check — transient errors happen
      console.error("Status check failed:", error);
    }
  };

  const fetchArtifacts = async () => {
    try {
      const { data } = await apiClient.get(`/packaging/${projectId}/artifacts`);
      setArtifacts(data.artifacts || []);
    } catch (error: any) {
      console.error("Failed to fetch artifacts:", error);
    }
  };

  const downloadArtifact = async (artifactId: number, name: string) => {
    try {
      const response = await apiClient.get(
        `/packaging/${projectId}/artifacts/${artifactId}/download`,
        { responseType: "blob" }
      );
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", `${name}.zip`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Downloaded! Extract the ZIP to find your installer 🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to download installer.");
    }
  };

  const handleTriggerBuild = async () => {
    setIsTriggering(true);
    try {
      await apiClient.post("/packaging/build", { project_id: projectId });
      toast.success("Build started! This takes 5-15 minutes 🐯🏗️");
      setBuildStatus("queued");
      pollStartedAtRef.current = Date.now();
      stopPolling();
      pollIntervalRef.current = setInterval(checkBuildStatus, POLL_INTERVAL_MS);
      // Check immediately too, don't wait a full interval for first update
      checkBuildStatus();
    } catch (error: any) {
      toast.error(
        error.message ||
          "Failed to start build. Windows packaging may not be configured yet."
      );
      setBuildStatus("idle");
    } finally {
      setIsTriggering(false);
    }
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
              The ZIP contains a starter code skeleton and test stubs — not a finished
              application. The Windows installer below packages the generated frontend
              as a desktop app shell; it does not yet bundle a working backend server.
            </p>
          </motion.div>

          {/* Download ZIP */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="flex flex-col sm:flex-row gap-3 mb-6"
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

          {/* Windows Installer — build & poll */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.25 }}
            className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
          >
            <div className="flex items-center gap-2 mb-3">
              <Monitor className="w-4 h-4 text-[var(--color-primary)]" />
              <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
                Windows Installer
              </h3>
              <span className="text-xs px-2 py-0.5 rounded-full bg-[var(--color-warning-light)] text-[var(--color-warning)] font-medium">
                Experimental
              </span>
            </div>

            <AnimatePresence mode="wait">
              {buildStatus === "idle" && (
                <motion.div
                  key="idle"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  <p className="text-xs text-[var(--color-text-secondary)] mb-4 leading-relaxed">
                    Build a real Windows .msi/.exe installer from your generated frontend.
                    This takes 5-15 minutes and requires packaging to be configured on
                    the backend.
                  </p>
                  <button
                    onClick={handleTriggerBuild}
                    disabled={isTriggering}
                    className="w-full py-3 rounded-xl border border-[var(--color-primary)] text-[var(--color-primary)] font-semibold text-sm hover:bg-[var(--color-primary-light)] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
                  >
                    {isTriggering ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Package className="w-4 h-4" />
                    )}
                    Build Windows Installer
                  </button>
                </motion.div>
              )}

              {(buildStatus === "queued" || buildStatus === "in_progress") && (
                <motion.div
                  key="building"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex flex-col items-center gap-3 py-4"
                >
                  <Loader2 className="w-6 h-6 text-[var(--color-primary)] animate-spin" />
                  <p className="text-sm text-[var(--color-text-primary)] font-medium">
                    {buildStatus === "queued" ? "Build queued..." : "Building your installer..."}
                  </p>
                  <p className="text-xs text-[var(--color-text-tertiary)] text-center">
                    This usually takes 5-15 minutes. Feel free to leave this page —
                    come back and check later.
                  </p>
                  {buildRunUrl && (
                    <a
                      href={buildRunUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-[var(--color-primary)] hover:underline flex items-center gap-1"
                    >
                      View live build log <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </motion.div>
              )}

              {buildStatus === "completed" && (
                <motion.div
                  key="completed"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex flex-col gap-3"
                >
                  <div className="flex items-center gap-2 text-[var(--color-success)]">
                    <CheckCircle2 className="w-4 h-4" />
                    <p className="text-sm font-medium">Build succeeded!</p>
                  </div>
                  {artifacts.length > 0 ? (
                    <div className="space-y-2">
                      {artifacts.map((artifact) => (
                        <div
                          key={artifact.id}
                          className="flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg bg-[var(--color-surface-raised)] border border-[var(--color-border)]"
                        >
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-mono text-[var(--color-text-primary)] truncate">
                              {artifact.name}
                            </p>
                            <p className="text-xs text-[var(--color-text-tertiary)]">
                              {(artifact.size_bytes / 1024 / 1024).toFixed(1)} MB
                            </p>
                          </div>
                          <button
                            onClick={() => downloadArtifact(artifact.id, artifact.name)}
                            className="px-3 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors flex items-center gap-1.5 flex-shrink-0"
                          >
                            <Download className="w-3.5 h-3.5" />
                            Download
                          </button>
                        </div>
                      ))}
                      <p className="text-xs text-[var(--color-text-tertiary)] text-center pt-1">
                        Files download as .zip — extract to find the installer inside.
                      </p>
                    </div>
                  ) : (
                    <p className="text-xs text-[var(--color-text-tertiary)]">
                      Build succeeded but no artifact was found. Check the build log.
                    </p>
                  )}
                </motion.div>
              )}

              {buildStatus === "failed" && (
                <motion.div
                  key="failed"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex flex-col gap-3"
                >
                  <div className="flex items-center gap-2 text-[var(--color-error)]">
                    <AlertCircle className="w-4 h-4" />
                    <p className="text-sm font-medium">Build failed</p>
                  </div>
                  <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
                    Something went wrong during packaging — this is an experimental
                    feature and failures are expected while it's being refined.
                  </p>
                  {buildRunUrl && (
                    <a
                      href={buildRunUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-[var(--color-primary)] hover:underline flex items-center gap-1"
                    >
                      View build log for details <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                  <button
                    onClick={() => setBuildStatus("idle")}
                    className="w-full py-2.5 rounded-xl border border-[var(--color-border)] text-[var(--color-text-primary)] font-medium text-sm hover:bg-[var(--color-surface-raised)] transition-colors"
                  >
                    Try Again
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
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
