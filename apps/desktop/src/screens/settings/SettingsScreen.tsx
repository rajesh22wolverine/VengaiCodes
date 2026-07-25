import { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { motion } from "framer-motion";
import { Check, Cpu, Loader2, Plus, Radar, Trash2 } from "lucide-react";
import toast from "react-hot-toast";

import { AppDispatch, RootState } from "@/store";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import {
  AIProviderType,
  createAIConfig,
  deleteAIConfig,
  fetchAIConfigs,
  setActiveAIConfig,
  useDefaultAI,
} from "@/store/slices/aiConfigSlice";

const PROVIDER_LABELS: Record<AIProviderType, string> = {
  groq: "Groq (your own key)",
  openai: "OpenAI (your own key)",
  anthropic: "Anthropic Claude (your own key)",
  custom: "Custom endpoint (self-hosted / local)",
};

// Uncensored AI Studio's local llama.cpp server — the verified "USB pendrive
// AI model" case this button is built for. Always available at /health.
const LOCAL_STUDIO_URL = "http://127.0.0.1:10086";

export default function SettingsScreen() {
  const dispatch = useDispatch<AppDispatch>();
  const { configs, isLoading, isSaving } = useSelector((state: RootState) => state.aiConfig);

  const [showForm, setShowForm] = useState(false);
  const [isDetecting, setIsDetecting] = useState(false);
  const [providerType, setProviderType] = useState<AIProviderType>("groq");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modelName, setModelName] = useState("");
  const [label, setLabel] = useState("");

  useEffect(() => {
    dispatch(fetchAIConfigs());
  }, [dispatch]);

  const activeConfig = configs.find((c) => c.is_active);

  const resetForm = () => {
    setProviderType("groq");
    setBaseUrl("");
    setApiKey("");
    setModelName("");
    setLabel("");
    setShowForm(false);
  };

  const handleSave = async () => {
    if (!modelName.trim() || !label.trim()) {
      toast.error("Model name and a label are required.");
      return;
    }
    if (providerType === "custom" && !baseUrl.trim()) {
      toast.error("A base URL is required for a custom endpoint.");
      return;
    }

    const result = await dispatch(
      createAIConfig({
        provider_type: providerType,
        base_url: baseUrl.trim() || undefined,
        api_key: apiKey.trim() || undefined,
        model_name: modelName.trim(),
        label: label.trim(),
        is_active: true,
      })
    );

    if (createAIConfig.fulfilled.match(result)) {
      toast.success(`Now using "${result.payload.label}" 🐯`);
      resetForm();
    } else {
      toast.error((result.payload as string) || "Failed to save AI model.");
    }
  };

  const handleUseDefault = async () => {
    await dispatch(useDefaultAI(activeConfig?.id));
    toast.success("Switched back to VengaiCode's default AI.");
  };

  const handleSetActive = async (id: string) => {
    const result = await dispatch(setActiveAIConfig(id));
    if (setActiveAIConfig.fulfilled.match(result)) {
      toast.success(`Now using "${result.payload.label}" 🐯`);
    }
  };

  const handleDelete = async (id: string) => {
    await dispatch(deleteAIConfig(id));
    toast.success("Removed.");
  };

  const detectLocalModel = async () => {
    setIsDetecting(true);
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2500);
      const res = await fetch(`${LOCAL_STUDIO_URL}/health`, { signal: controller.signal });
      clearTimeout(timeoutId);
      if (!res.ok) throw new Error("not reachable");

      setShowForm(true);
      setProviderType("custom");
      setBaseUrl(`${LOCAL_STUDIO_URL}/v1`);
      setLabel("Local AI model");
      toast.success("Found a local AI server running — review and save below.");
    } catch {
      toast.error("No local AI model detected on this machine.");
    } finally {
      setIsDetecting(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--color-background)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <BabyTiger size={36} expression="happy" />
        <div>
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">Settings</h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">Manage your account and AI model</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-8">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-2xl mx-auto space-y-6"
        >
          {/* ── AI Model section ── */}
          <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 space-y-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-sm font-semibold text-[var(--color-text-primary)] flex items-center gap-2">
                  <Cpu className="w-4 h-4" /> AI Model
                </h2>
                <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                  Use VengaiCode's default AI, or bring your own — your own provider key or a
                  self-hosted local model. Switching to your own never uses VengaiCode's AI quota.
                </p>
              </div>
              <button
                onClick={detectLocalModel}
                disabled={isDetecting}
                className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-primary)] hover:text-[var(--color-primary)] transition-colors disabled:opacity-60"
              >
                {isDetecting ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Radar className="w-3.5 h-3.5" />
                )}
                Detect local AI model
              </button>
            </div>

            {/* Current status */}
            <div className="flex items-center justify-between rounded-xl bg-[var(--color-background)] border border-[var(--color-border)] px-4 py-3">
              <div>
                <p className="text-xs text-[var(--color-text-tertiary)]">Currently using</p>
                <p className="text-sm font-medium text-[var(--color-text-primary)]">
                  {activeConfig ? activeConfig.label : "VengaiCode default (Ollama + Groq)"}
                </p>
              </div>
              {activeConfig && (
                <button
                  onClick={handleUseDefault}
                  className="text-xs font-medium text-[var(--color-primary)] hover:text-[var(--color-primary-hover)]"
                >
                  Switch to default
                </button>
              )}
            </div>

            {/* Saved configs */}
            {isLoading ? (
              <div className="flex justify-center py-4">
                <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-tertiary)]" />
              </div>
            ) : (
              configs.length > 0 && (
                <div className="space-y-2">
                  {configs.map((config) => (
                    <div
                      key={config.id}
                      className="flex items-center justify-between rounded-xl border border-[var(--color-border)] px-4 py-3"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">
                            {config.label}
                          </p>
                          {config.is_active && (
                            <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-[var(--color-primary-light)] text-[var(--color-primary)] text-[10px] font-semibold">
                              <Check className="w-2.5 h-2.5" /> Active
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-[var(--color-text-tertiary)] truncate">
                          {PROVIDER_LABELS[config.provider_type]} · {config.model_name}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {!config.is_active && (
                          <button
                            onClick={() => handleSetActive(config.id)}
                            className="text-xs font-medium text-[var(--color-primary)] hover:text-[var(--color-primary-hover)]"
                          >
                            Use this
                          </button>
                        )}
                        <button
                          onClick={() => handleDelete(config.id)}
                          className="p-1.5 rounded-lg hover:bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)] hover:text-[var(--color-error)] transition-colors"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )
            )}

            {/* Add form */}
            {showForm ? (
              <div className="space-y-3 pt-2 border-t border-[var(--color-border)]">
                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                    Provider
                  </label>
                  <select
                    value={providerType}
                    onChange={(e) => setProviderType(e.target.value as AIProviderType)}
                    className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                  >
                    {(Object.entries(PROVIDER_LABELS) as [AIProviderType, string][]).map(
                      ([value, providerLabel]) => (
                        <option key={value} value={value}>
                          {providerLabel}
                        </option>
                      )
                    )}
                  </select>
                </div>

                {providerType === "custom" && (
                  <div>
                    <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                      Base URL *
                    </label>
                    <input
                      value={baseUrl}
                      onChange={(e) => setBaseUrl(e.target.value)}
                      placeholder="http://127.0.0.1:10086/v1"
                      className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                    />
                  </div>
                )}

                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                    API key{" "}
                    {providerType === "custom" && "(optional — local servers usually don't need one)"}
                  </label>
                  <input
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    type="password"
                    placeholder={providerType === "custom" ? "Leave blank if not required" : "sk-..."}
                    className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                    Model name *
                  </label>
                  <input
                    value={modelName}
                    onChange={(e) => setModelName(e.target.value)}
                    placeholder="e.g. llama3-70b-8192, or whatever's currently loaded locally"
                    className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                    Label *
                  </label>
                  <input
                    value={label}
                    onChange={(e) => setLabel(e.target.value)}
                    placeholder="e.g. My local Qwen (USB)"
                    className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                  />
                </div>

                <div className="flex gap-2 pt-1">
                  <button
                    onClick={handleSave}
                    disabled={isSaving}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-white text-sm font-semibold transition-all disabled:opacity-60"
                  >
                    {isSaving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    Save & use this model
                  </button>
                  <button
                    onClick={resetForm}
                    className="px-4 py-2 rounded-xl border border-[var(--color-border)] text-sm font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)] transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setShowForm(true)}
                className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-primary)] hover:text-[var(--color-primary-hover)]"
              >
                <Plus className="w-3.5 h-3.5" /> Add AI model configuration
              </button>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
