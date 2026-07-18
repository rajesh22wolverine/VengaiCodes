import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft, CheckCircle2, Users, Target, Sparkles,
  Smartphone, DollarSign, BookOpen, Code2, Loader2, ThumbsUp
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import ChatPanel from "@/components/chat/ChatPanel";

interface RequirementsDocument {
  overview: string;
  problem_statement: string;
  target_users: string;
  key_features: string[];
  platforms: string[];
  monetization: string;
  reference_apps: string[];
  user_stories: string[];
  tech_recommendations: string;
}

export default function RequirementsScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [requirements, setRequirements] = useState<RequirementsDocument | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/requirements/${projectId}`);
      setRequirements(data.requirements);
      setIsLoading(false);
    } catch {
      // Not generated yet — generate now
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/requirements/generate", {
        project_id: projectId,
      });
      setRequirements(data.requirements);
      toast.success("Your requirements document is ready! 🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to generate requirements.");
      navigate(`/project/${projectId}/wizard`);
    } finally {
      setIsGenerating(false);
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
      await apiClient.post("/requirements/approve", {
        project_id: projectId,
        approved: true,
      });
      toast.success("Requirements approved! Next: UI/UX Design 🐯");
      navigate(`/project/${projectId}/uiux`);
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
            ? "Baby Tiger is organizing your requirements... 🐯"
            : "Loading..."}
        </p>
      </div>
    );
  }

  if (!requirements) return null;

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
            Requirements Document
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Phase 1 of 7 — Review and approve to continue
          </p>
        </div>
      </div>

      {/* Document content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-6">

          {/* Overview */}
          <Section icon={Sparkles} title="Overview">
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {requirements.overview}
            </p>
          </Section>

          {/* Problem Statement */}
          <Section icon={Target} title="Problem Statement">
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {requirements.problem_statement}
            </p>
          </Section>

          {/* Target Users */}
          <Section icon={Users} title="Target Users">
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {requirements.target_users}
            </p>
          </Section>

          {/* Key Features */}
          <Section icon={CheckCircle2} title="Key Features">
            <ul className="space-y-2">
              {requirements.key_features.map((feature, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-[var(--color-text-secondary)]">
                  <CheckCircle2 className="w-4 h-4 text-[var(--color-success)] flex-shrink-0 mt-0.5" />
                  <span className="capitalize">{feature}</span>
                </li>
              ))}
            </ul>
          </Section>

          {/* Platforms */}
          <Section icon={Smartphone} title="Platforms">
            <div className="flex flex-wrap gap-2">
              {requirements.platforms.map((platform, i) => (
                <span
                  key={i}
                  className="px-3 py-1.5 rounded-lg bg-[var(--color-primary-light)] text-[var(--color-primary)] text-xs font-medium"
                >
                  {platform}
                </span>
              ))}
            </div>
          </Section>

          {/* Monetization */}
          <Section icon={DollarSign} title="Monetization">
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {requirements.monetization}
            </p>
          </Section>

          {/* User Stories */}
          <Section icon={BookOpen} title="User Stories">
            <ul className="space-y-3">
              {requirements.user_stories.map((story, i) => (
                <li
                  key={i}
                  className="text-sm text-[var(--color-text-secondary)] leading-relaxed p-3 rounded-xl bg-[var(--color-surface-raised)] border-l-2 border-[var(--color-primary)]"
                >
                  {story}
                </li>
              ))}
            </ul>
          </Section>

          {/* Tech Recommendations */}
          <Section icon={Code2} title="Tech Recommendations">
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {requirements.tech_recommendations}
            </p>
          </Section>

          {/* Reference Apps */}
          {requirements.reference_apps.length > 0 && (
            <Section icon={Sparkles} title="Similar Apps">
              <div className="flex flex-wrap gap-2">
                {requirements.reference_apps.map((app, i) => (
                  <span
                    key={i}
                    className="px-3 py-1.5 rounded-lg bg-[var(--color-surface-raised)] text-[var(--color-text-secondary)] text-xs font-medium"
                  >
                    {app}
                  </span>
                ))}
              </div>
            </Section>
          )}
        </div>
      </div>

      {/* Footer — approve action */}
      <div className="flex-shrink-0 px-6 py-4 border-t border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Review everything above. Once approved, Baby Tiger moves to UI/UX Design 🎨
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
      <ChatPanel projectId={projectId} phase="requirements" />
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4 text-[var(--color-primary)]" />
        <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
          {title}
        </h3>
      </div>
      {children}
    </motion.div>
  );
}
