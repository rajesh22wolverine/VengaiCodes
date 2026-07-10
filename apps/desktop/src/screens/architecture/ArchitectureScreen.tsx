import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft, Layers, Database, Webhook, Package,
  Loader2, ThumbsUp
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

interface TechStack {
  frontend: string;
  backend: string;
  database: string;
  hosting: string;
}

interface DatabaseTable {
  name: string;
  purpose: string;
  key_fields: string[];
}

interface APIEndpoint {
  method: string;
  path: string;
  purpose: string;
}

interface ArchitectureDesign {
  architecture_summary: string;
  tech_stack: TechStack;
  database_tables: DatabaseTable[];
  api_endpoints: APIEndpoint[];
  third_party_services: string[];
}

const METHOD_COLORS: Record<string, string> = {
  GET: "var(--color-success)",
  POST: "var(--color-primary)",
  PUT: "var(--color-warning)",
  PATCH: "var(--color-warning)",
  DELETE: "var(--color-error)",
};

export default function ArchitectureScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [architecture, setArchitecture] = useState<ArchitectureDesign | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/architecture/${projectId}`);
      setArchitecture(data.architecture);
      setIsLoading(false);
    } catch {
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/architecture/generate", {
        project_id: projectId,
      });
      setArchitecture(data.architecture);
      toast.success("Your architecture is ready! 🏗️🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to generate architecture.");
      navigate(`/project/${projectId}/uiux`);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleApprove = async () => {
    setIsApproving(true);
    try {
      await apiClient.post("/architecture/approve", {
        project_id: projectId,
        approved: true,
      });
      toast.success("Architecture approved! Next: API Builder 🐯");
      navigate(`/project/${projectId}/codegen`);
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
            ? "Baby Tiger is planning your architecture... 🏗️🐯"
            : "Loading..."}
        </p>
      </div>
    );
  }

  if (!architecture) return null;

  const stackEntries = Object.entries(architecture.tech_stack) as [keyof TechStack, string][];

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
            Architecture
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Phase 3 of 7 — Review and approve to continue
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-6">

          {/* Summary */}
          <Section icon={Layers} title="Architecture Summary">
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {architecture.architecture_summary}
            </p>
          </Section>

          {/* Tech Stack */}
          <Section icon={Package} title="Tech Stack">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {stackEntries.map(([key, value]) => (
                <div
                  key={key}
                  className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
                >
                  <p className="text-xs font-semibold text-[var(--color-primary)] uppercase tracking-wider mb-1.5">
                    {key}
                  </p>
                  <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
                    {value}
                  </p>
                </div>
              ))}
            </div>
          </Section>

          {/* Database Tables */}
          <Section icon={Database} title={`Database Tables (${architecture.database_tables.length})`}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {architecture.database_tables.map((table, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <Database className="w-3.5 h-3.5 text-[var(--color-primary)] flex-shrink-0" />
                    <h4 className="text-sm font-semibold text-[var(--color-text-primary)] font-mono">
                      {table.name}
                    </h4>
                  </div>
                  <p className="text-xs text-[var(--color-text-secondary)] mb-3 leading-relaxed">
                    {table.purpose}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {table.key_fields.map((field, j) => (
                      <span
                        key={j}
                        className="px-2 py-1 rounded-md bg-[var(--color-surface)] text-[var(--color-text-tertiary)] text-xs font-mono border border-[var(--color-border)]"
                      >
                        {field}
                      </span>
                    ))}
                  </div>
                </motion.div>
              ))}
            </div>
          </Section>

          {/* API Endpoints */}
          <Section icon={Webhook} title={`API Endpoints (${architecture.api_endpoints.length})`}>
            <div className="space-y-2">
              {architecture.api_endpoints.map((endpoint, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3"
                >
                  <span
                    className="px-2 py-1 rounded-md text-xs font-bold text-white flex-shrink-0 font-mono"
                    style={{
                      backgroundColor: METHOD_COLORS[endpoint.method.toUpperCase()] || "var(--color-text-tertiary)",
                    }}
                  >
                    {endpoint.method.toUpperCase()}
                  </span>
                  <code className="text-xs font-mono text-[var(--color-text-primary)] flex-shrink-0">
                    {endpoint.path}
                  </code>
                  <span className="text-xs text-[var(--color-text-tertiary)] truncate">
                    {endpoint.purpose}
                  </span>
                </div>
              ))}
            </div>
          </Section>

          {/* Third-Party Services */}
          {architecture.third_party_services.length > 0 && (
            <Section icon={Package} title="Third-Party Services">
              <div className="flex flex-wrap gap-2">
                {architecture.third_party_services.map((service, i) => (
                  <span
                    key={i}
                    className="px-3 py-1.5 rounded-lg bg-[var(--color-primary-light)] text-[var(--color-primary)] text-xs font-medium"
                  >
                    {service}
                  </span>
                ))}
              </div>
            </Section>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="flex-shrink-0 px-6 py-4 border-t border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Review the architecture above. Once approved, Baby Tiger starts building 🚀
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
