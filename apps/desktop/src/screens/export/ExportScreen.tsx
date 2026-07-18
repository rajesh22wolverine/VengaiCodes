import { useEffect, useState, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Download, Loader2, PartyPopper, FileText,
  Code2, TestTube2, Palette, Layers, CheckCircle2, Package,
  AlertCircle, ExternalLink, Monitor, BookOpen, Smartphone, Terminal
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import ChatPanel from "@/components/chat/ChatPanel";

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
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);
  const [includeO3DE, setIncludeO3DE] = useState(false);
  const [appName, setAppName] = useState("");

  const [buildStatus, setBuildStatus] = useState<BuildStatus>("idle");
  const [buildRunUrl, setBuildRunUrl] = useState<string | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [artifacts, setArtifacts] = useState<BuildArtifact[]>([]);

  const [androidBuildStatus, setAndroidBuildStatus] = useState<BuildStatus>("idle");
  const [androidBuildRunUrl, setAndroidBuildRunUrl] = useState<string | null>(null);
  const [isTriggeringAndroid, setIsTriggeringAndroid] = useState(false);
  const [androidArtifacts, setAndroidArtifacts] = useState<BuildArtifact[]>([]);

  const [linuxBuildStatus, setLinuxBuildStatus] = useState<BuildStatus>("idle");
  const [linuxBuildRunUrl, setLinuxBuildRunUrl] = useState<string | null>(null);
  const [isTriggeringLinux, setIsTriggeringLinux] = useState(false);
  const [linuxArtifacts, setLinuxArtifacts] = useState<BuildArtifact[]>([]);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollStartedAtRef = useRef<number | null>(null);
  const androidPollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const androidPollStartedAtRef = useRef<number | null>(null);
  const linuxPollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const linuxPollStartedAtRef = useRef<number | null>(null);

  useEffect(() => {
    loadSummary();
    return () => {
      stopPolling();
      stopAndroidPolling();
      stopLinuxPolling();
    };
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
        params: {
          include_o3de: includeO3DE,
          app_name: appName.trim() || undefined,
        },
      });
      const contentDisposition = response.headers["content-disposition"] || "";
      const filenameMatch = contentDisposition.match(/filename\s*=\s*"?([^";]+)"?/i);
      const downloadName = filenameMatch?.[1] || `${(appName || summary?.name || "vengaicode_project").trim()}.zip`;
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", downloadName);
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

  // ── Android APK build ──

  const stopAndroidPolling = () => {
    if (androidPollIntervalRef.current) {
      clearInterval(androidPollIntervalRef.current);
      androidPollIntervalRef.current = null;
    }
  };

  const checkAndroidBuildStatus = async () => {
    try {
      const { data } = await apiClient.get(`/packaging/android/${projectId}/status`);
      setAndroidBuildRunUrl(data.run_url || null);

      if (data.status === "completed") {
        stopAndroidPolling();
        if (data.conclusion === "success") {
          setAndroidBuildStatus("completed");
          toast.success("Your APK is ready! 🐯🎉");
          fetchAndroidArtifacts();
        } else {
          setAndroidBuildStatus("failed");
          toast.error("Build failed. Check the build log for details.");
        }
        return;
      }

      setAndroidBuildStatus(data.status === "queued" ? "queued" : "in_progress");

      if (
        androidPollStartedAtRef.current &&
        Date.now() - androidPollStartedAtRef.current > POLL_TIMEOUT_MS
      ) {
        stopAndroidPolling();
        toast.error("Build is taking longer than expected. Check the log directly.");
      }
    } catch (error: any) {
      console.error("Status check failed:", error);
    }
  };

  const fetchAndroidArtifacts = async () => {
    try {
      const { data } = await apiClient.get(`/packaging/android/${projectId}/artifacts`);
      setAndroidArtifacts(data.artifacts || []);
    } catch (error: any) {
      console.error("Failed to fetch artifacts:", error);
    }
  };

  const downloadAndroidArtifact = async (artifactId: number, name: string) => {
    try {
      const response = await apiClient.get(
        `/packaging/android/${projectId}/artifacts/${artifactId}/download`,
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
      toast.success("Downloaded! Extract the ZIP to find your APK 🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to download APK.");
    }
  };

  const handleTriggerAndroidBuild = async () => {
    setIsTriggeringAndroid(true);
    try {
      await apiClient.post("/packaging/android/build", { project_id: projectId });
      toast.success("Build started! This takes 10-25 minutes 🐯🏗️");
      setAndroidBuildStatus("queued");
      androidPollStartedAtRef.current = Date.now();
      stopAndroidPolling();
      androidPollIntervalRef.current = setInterval(checkAndroidBuildStatus, POLL_INTERVAL_MS);
      checkAndroidBuildStatus();
    } catch (error: any) {
      toast.error(
        error.message ||
          "Failed to start build. Android packaging may not be configured yet."
      );
      setAndroidBuildStatus("idle");
    } finally {
      setIsTriggeringAndroid(false);
    }
  };

  // ── Linux installer build ──

  const stopLinuxPolling = () => {
    if (linuxPollIntervalRef.current) {
      clearInterval(linuxPollIntervalRef.current);
      linuxPollIntervalRef.current = null;
    }
  };

  const checkLinuxBuildStatus = async () => {
    try {
      const { data } = await apiClient.get(`/packaging/linux/${projectId}/status`);
      setLinuxBuildRunUrl(data.run_url || null);

      if (data.status === "completed") {
        stopLinuxPolling();
        if (data.conclusion === "success") {
          setLinuxBuildStatus("completed");
          toast.success("Your installer is ready! 🐯🎉");
          fetchLinuxArtifacts();
        } else {
          setLinuxBuildStatus("failed");
          toast.error("Build failed. Check the build log for details.");
        }
        return;
      }

      setLinuxBuildStatus(data.status === "queued" ? "queued" : "in_progress");

      if (
        linuxPollStartedAtRef.current &&
        Date.now() - linuxPollStartedAtRef.current > POLL_TIMEOUT_MS
      ) {
        stopLinuxPolling();
        toast.error("Build is taking longer than expected. Check the log directly.");
      }
    } catch (error: any) {
      console.error("Status check failed:", error);
    }
  };

  const fetchLinuxArtifacts = async () => {
    try {
      const { data } = await apiClient.get(`/packaging/linux/${projectId}/artifacts`);
      setLinuxArtifacts(data.artifacts || []);
    } catch (error: any) {
      console.error("Failed to fetch artifacts:", error);
    }
  };

  const downloadLinuxArtifact = async (artifactId: number, name: string) => {
    try {
      const response = await apiClient.get(
        `/packaging/linux/${projectId}/artifacts/${artifactId}/download`,
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

  const handleTriggerLinuxBuild = async () => {
    setIsTriggeringLinux(true);
    try {
      await apiClient.post("/packaging/linux/build", { project_id: projectId });
      toast.success("Build started! This takes 5-15 minutes 🐯🏗️");
      setLinuxBuildStatus("queued");
      linuxPollStartedAtRef.current = Date.now();
      stopLinuxPolling();
      linuxPollIntervalRef.current = setInterval(checkLinuxBuildStatus, POLL_INTERVAL_MS);
      checkLinuxBuildStatus();
    } catch (error: any) {
      toast.error(
        error.message ||
          "Failed to start build. Linux packaging may not be configured yet."
      );
      setLinuxBuildStatus("idle");
    } finally {
      setIsTriggeringLinux(false);
    }
  };

  const platforms = (summary?.platforms || []).map((platform) => String(platform).toLowerCase());
  const hasDesktopTargets = platforms.some((platform) =>
    ["desktop_windows", "desktop_mac", "desktop_linux", "all"].includes(platform)
  );
  const hasMobileTargets = platforms.some((platform) =>
    ["mobile_ios", "mobile_android", "all"].includes(platform)
  );

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

          {/* Download options */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 mb-6"
          >
            <div className="flex items-center gap-2 mb-4">
              <Download className="w-4 h-4 text-[var(--color-primary)]" />
              <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
                Export your app
              </h3>
            </div>

            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-2">
              App name
            </label>
            <input
              value={appName}
              onChange={(event) => setAppName(event.target.value)}
              placeholder="Enter your app name"
              className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
            />

            <label className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)] mt-3">
              <input
                type="checkbox"
                checked={includeO3DE}
                onChange={(e) => setIncludeO3DE(e.target.checked)}
                className="w-4 h-4 rounded"
              />
              <span>Include O3DE template files (experimental)</span>
            </label>

            <div className="grid gap-3 mt-4 sm:grid-cols-2">
              <button
                onClick={handleDownload}
                disabled={isDownloading}
                className="py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center justify-center gap-2 shadow-md hover:shadow-lg"
              >
                {isDownloading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Download className="w-4 h-4" />
                )}
                Download Project ZIP
              </button>
              <button
                onClick={handleDownloadDocs}
                disabled={isDownloadingDocs}
                className="py-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-primary)] font-semibold text-sm hover:bg-[var(--color-surface)] transition-colors flex items-center justify-center gap-2"
              >
                {isDownloadingDocs ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <BookOpen className="w-4 h-4" />
                )}
                Export Documentation
              </button>
            </div>
            <div className="mt-3">
              <button
                onClick={handleFinish}
                className="w-full py-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-primary)] font-semibold text-sm hover:bg-[var(--color-surface)] transition-colors flex items-center justify-center gap-2"
              >
                <PartyPopper className="w-4 h-4" />
                Finish & Return Home
              </button>
            </div>

            <div className="grid gap-3 mt-4 md:grid-cols-2">
              {hasDesktopTargets && (
                <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] p-3">
                  <p className="text-xs font-semibold text-[var(--color-text-primary)] mb-1">
                    Desktop package
                  </p>
                  <p className="text-xs text-[var(--color-text-secondary)] mb-3">
                    Build and download a desktop-ready installer for this project.
                  </p>
                  <button
                    onClick={() => setBuildStatus("idle")}
                    className="w-full py-2 rounded-lg border border-[var(--color-primary)] text-[var(--color-primary)] text-xs font-semibold hover:bg-[var(--color-primary-light)] transition-colors"
                  >
                    Open installer options
                  </button>
                </div>
              )}
              {hasMobileTargets && (
                <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] p-3">
                  <p className="text-xs font-semibold text-[var(--color-text-primary)] mb-1">
                    Mobile package
                  </p>
                  <p className="text-xs text-[var(--color-text-secondary)] mb-3">
                    Download the starter mobile bundle for Android and iOS targets.
                  </p>
                  <button
                    onClick={handleDownload}
                    disabled={isDownloading}
                    className="w-full py-2 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60"
                  >
                    Download mobile bundle
                  </button>
                </div>
              )}
            </div>
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

          {/* Linux Installer — build & poll */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.28 }}
            className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 mt-6"
          >
            <div className="flex items-center gap-2 mb-3">
              <Terminal className="w-4 h-4 text-[var(--color-primary)]" />
              <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
                Linux Installer
              </h3>
              <span className="text-xs px-2 py-0.5 rounded-full bg-[var(--color-warning-light)] text-[var(--color-warning)] font-medium">
                Experimental
              </span>
            </div>

            <AnimatePresence mode="wait">
              {linuxBuildStatus === "idle" && (
                <motion.div
                  key="linux-idle"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                >
                  <p className="text-xs text-[var(--color-text-secondary)] mb-4 leading-relaxed">
                    Build a real Linux .deb/.AppImage installer from your generated frontend.
                    This takes 5-15 minutes and requires packaging to be configured on
                    the backend.
                  </p>
                  <button
                    onClick={handleTriggerLinuxBuild}
                    disabled={isTriggeringLinux}
                    className="w-full py-3 rounded-xl border border-[var(--color-primary)] text-[var(--color-primary)] font-semibold text-sm hover:bg-[var(--color-primary-light)] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
                  >
                    {isTriggeringLinux ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Package className="w-4 h-4" />
                    )}
                    Build Linux Installer
                  </button>
                </motion.div>
              )}

              {(linuxBuildStatus === "queued" || linuxBuildStatus === "in_progress") && (
                <motion.div
                  key="linux-building"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex flex-col items-center gap-3 py-4"
                >
                  <Loader2 className="w-6 h-6 text-[var(--color-primary)] animate-spin" />
                  <p className="text-sm text-[var(--color-text-primary)] font-medium">
                    {linuxBuildStatus === "queued" ? "Build queued..." : "Building your installer..."}
                  </p>
                  <p className="text-xs text-[var(--color-text-tertiary)] text-center">
                    This usually takes 5-15 minutes. Feel free to leave this page —
                    come back and check later.
                  </p>
                  {linuxBuildRunUrl && (
                    <a
                      href={linuxBuildRunUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-[var(--color-primary)] hover:underline flex items-center gap-1"
                    >
                      View live build log <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </motion.div>
              )}

              {linuxBuildStatus === "completed" && (
                <motion.div
                  key="linux-completed"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="flex flex-col gap-3"
                >
                  <div className="flex items-center gap-2 text-[var(--color-success)]">
                    <CheckCircle2 className="w-4 h-4" />
                    <p className="text-sm font-medium">Build succeeded!</p>
                  </div>
                  {linuxArtifacts.length > 0 ? (
                    <div className="space-y-2">
                      {linuxArtifacts.map((artifact) => (
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
                            onClick={() => downloadLinuxArtifact(artifact.id, artifact.name)}
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

              {linuxBuildStatus === "failed" && (
                <motion.div
                  key="linux-failed"
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
                  {linuxBuildRunUrl && (
                    <a
                      href={linuxBuildRunUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-[var(--color-primary)] hover:underline flex items-center gap-1"
                    >
                      View build log for details <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                  <button
                    onClick={() => setLinuxBuildStatus("idle")}
                    className="w-full py-2.5 rounded-xl border border-[var(--color-border)] text-[var(--color-text-primary)] font-medium text-sm hover:bg-[var(--color-surface-raised)] transition-colors"
                  >
                    Try Again
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>

          {/* Android APK — build & poll */}
          {hasMobileTargets && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 mt-6"
            >
              <div className="flex items-center gap-2 mb-3">
                <Smartphone className="w-4 h-4 text-[var(--color-primary)]" />
                <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
                  Android APK
                </h3>
                <span className="text-xs px-2 py-0.5 rounded-full bg-[var(--color-warning-light)] text-[var(--color-warning)] font-medium">
                  Experimental
                </span>
              </div>

              <AnimatePresence mode="wait">
                {androidBuildStatus === "idle" && (
                  <motion.div
                    key="android-idle"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                  >
                    <p className="text-xs text-[var(--color-text-secondary)] mb-4 leading-relaxed">
                      Build a real installable Android .apk from your generated frontend.
                      This takes 10-25 minutes and requires packaging to be configured on
                      the backend.
                    </p>
                    <button
                      onClick={handleTriggerAndroidBuild}
                      disabled={isTriggeringAndroid}
                      className="w-full py-3 rounded-xl border border-[var(--color-primary)] text-[var(--color-primary)] font-semibold text-sm hover:bg-[var(--color-primary-light)] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
                    >
                      {isTriggeringAndroid ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Package className="w-4 h-4" />
                      )}
                      Build Android APK
                    </button>
                  </motion.div>
                )}

                {(androidBuildStatus === "queued" || androidBuildStatus === "in_progress") && (
                  <motion.div
                    key="android-building"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="flex flex-col items-center gap-3 py-4"
                  >
                    <Loader2 className="w-6 h-6 text-[var(--color-primary)] animate-spin" />
                    <p className="text-sm text-[var(--color-text-primary)] font-medium">
                      {androidBuildStatus === "queued" ? "Build queued..." : "Building your APK..."}
                    </p>
                    <p className="text-xs text-[var(--color-text-tertiary)] text-center">
                      This usually takes 10-25 minutes. Feel free to leave this page —
                      come back and check later.
                    </p>
                    {androidBuildRunUrl && (
                      <a
                        href={androidBuildRunUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-[var(--color-primary)] hover:underline flex items-center gap-1"
                      >
                        View live build log <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                  </motion.div>
                )}

                {androidBuildStatus === "completed" && (
                  <motion.div
                    key="android-completed"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="flex flex-col gap-3"
                  >
                    <div className="flex items-center gap-2 text-[var(--color-success)]">
                      <CheckCircle2 className="w-4 h-4" />
                      <p className="text-sm font-medium">Build succeeded!</p>
                    </div>
                    {androidArtifacts.length > 0 ? (
                      <div className="space-y-2">
                        {androidArtifacts.map((artifact) => (
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
                              onClick={() => downloadAndroidArtifact(artifact.id, artifact.name)}
                              className="px-3 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors flex items-center gap-1.5 flex-shrink-0"
                            >
                              <Download className="w-3.5 h-3.5" />
                              Download
                            </button>
                          </div>
                        ))}
                        <p className="text-xs text-[var(--color-text-tertiary)] text-center pt-1">
                          Files download as .zip — extract to find the .apk inside.
                        </p>
                      </div>
                    ) : (
                      <p className="text-xs text-[var(--color-text-tertiary)]">
                        Build succeeded but no artifact was found. Check the build log.
                      </p>
                    )}
                  </motion.div>
                )}

                {androidBuildStatus === "failed" && (
                  <motion.div
                    key="android-failed"
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
                    {androidBuildRunUrl && (
                      <a
                        href={androidBuildRunUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-[var(--color-primary)] hover:underline flex items-center gap-1"
                      >
                        View build log for details <ExternalLink className="w-3 h-3" />
                      </a>
                    )}
                    <button
                      onClick={() => setAndroidBuildStatus("idle")}
                      className="w-full py-2.5 rounded-xl border border-[var(--color-border)] text-[var(--color-text-primary)] font-medium text-sm hover:bg-[var(--color-surface-raised)] transition-colors"
                    >
                      Try Again
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          )}
        </div>
      </div>
      <ChatPanel projectId={projectId} phase="export" />
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
