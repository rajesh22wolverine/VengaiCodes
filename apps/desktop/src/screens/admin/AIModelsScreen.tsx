import { useEffect, useState } from "react";
import { motion, Reorder } from "framer-motion";
import {
  Check,
  GripVertical,
  Loader2,
  Plus,
  Server,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import toast from "react-hot-toast";

import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

// ─── Platform-default AI config (user_id IS NULL) — mirrors backend
// AdminAIConfigResponse in apps/backend/app/schemas/ai_config.py. These
// sit in every user's "bag" alongside their own BYO configs — see
// app/ai/orchestrator.get_effective_bag(). ───
type AdminProviderType = "groq" | "openai" | "anthropic" | "xai" | "custom" | "ollama";
type AdminTaskType = "codegen" | "general";

interface PlatformAIConfig {
  id: string;
  provider_type: AdminProviderType;
  base_url: string;
  has_api_key: boolean;
  model_name: string;
  label: string;
  is_active: boolean;
  order_index: number | null;
  task_type: AdminTaskType | null;
  created_at: string;
  updated_at: string;
}

const PROVIDER_LABELS: Record<AdminProviderType, string> = {
  groq: "Groq",
  openai: "OpenAI",
  anthropic: "Anthropic Claude",
  xai: "Grok / xAI",
  ollama: "Ollama (local or self-hosted)",
  custom: "Custom OpenAI-compatible endpoint",
};

const PROVIDERS_REQUIRING_KEY = new Set<AdminProviderType>(["groq", "openai", "anthropic", "xai"]);

interface FormState {
  provider_type: AdminProviderType;
  base_url: string;
  api_key: string;
  model_name: string;
  label: string;
  is_active: boolean;
  task_type: AdminTaskType | "";
}

const EMPTY_FORM: FormState = {
  provider_type: "groq",
  base_url: "",
  api_key: "",
  model_name: "",
  label: "",
  is_active: true,
  task_type: "",
};

export default function AIModelsScreen() {
  const [configs, setConfigs] = useState<PlatformAIConfig[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isReordering, setIsReordering] = useState(false);

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);

  const loadConfigs = async () => {
    setIsLoading(true);
    try {
      const { data } = await apiClient.get("/admin/ai-configs");
      setConfigs(data.configs || []);
    } catch (error: any) {
      toast.error(error.message || "Failed to load platform AI models.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadConfigs();
  }, []);

  const resetForm = () => {
    setForm(EMPTY_FORM);
    setShowForm(false);
    setEditingId(null);
  };

  const startEdit = (config: PlatformAIConfig) => {
    setForm({
      provider_type: config.provider_type,
      base_url: config.base_url,
      api_key: "",
      model_name: config.model_name,
      label: config.label,
      is_active: config.is_active,
      task_type: config.task_type || "",
    });
    setEditingId(config.id);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.model_name.trim() || !form.label.trim()) {
      toast.error("Model name and a label are required.");
      return;
    }
    if (form.provider_type === "custom" && !form.base_url.trim()) {
      toast.error("A base URL is required for a custom endpoint.");
      return;
    }
    if (PROVIDERS_REQUIRING_KEY.has(form.provider_type) && !editingId && !form.api_key.trim()) {
      toast.error(`An API key is required for ${PROVIDER_LABELS[form.provider_type]}.`);
      return;
    }

    setIsSaving(true);
    try {
      if (editingId) {
        const payload: Record<string, unknown> = {
          base_url: form.base_url.trim() || undefined,
          model_name: form.model_name.trim(),
          label: form.label.trim(),
          is_active: form.is_active,
          task_type: form.task_type || undefined,
          clear_task_type: !form.task_type,
        };
        if (form.api_key.trim()) payload.api_key = form.api_key.trim();
        const { data } = await apiClient.patch(`/admin/ai-configs/${editingId}`, payload);
        setConfigs((prev) => prev.map((c) => (c.id === editingId ? data.config : c)));
        toast.success(`"${data.config.label}" updated.`);
      } else {
        const { data } = await apiClient.post("/admin/ai-configs", {
          provider_type: form.provider_type,
          base_url: form.base_url.trim() || undefined,
          api_key: form.api_key.trim() || undefined,
          model_name: form.model_name.trim(),
          label: form.label.trim(),
          is_active: form.is_active,
          order_index: configs.length,
          task_type: form.task_type || undefined,
        });
        setConfigs((prev) => [...prev, data.config]);
        toast.success(`"${data.config.label}" added to every user's AI model bag 🐯`);
      }
      resetForm();
    } catch (error: any) {
      toast.error(error.message || "Failed to save.");
    } finally {
      setIsSaving(false);
    }
  };

  const handleToggleActive = async (config: PlatformAIConfig) => {
    try {
      const { data } = await apiClient.patch(`/admin/ai-configs/${config.id}`, {
        is_active: !config.is_active,
      });
      setConfigs((prev) => prev.map((c) => (c.id === config.id ? data.config : c)));
    } catch (error: any) {
      toast.error(error.message || "Failed to update.");
    }
  };

  const handleDelete = async (config: PlatformAIConfig) => {
    if (!confirm(`Remove "${config.label}" from every user's AI model bag?`)) return;
    try {
      await apiClient.delete(`/admin/ai-configs/${config.id}`);
      setConfigs((prev) => prev.filter((c) => c.id !== config.id));
      toast.success("Removed.");
    } catch (error: any) {
      toast.error(error.message || "Failed to delete.");
    }
  };

  const handleReorder = async (next: PlatformAIConfig[]) => {
    setConfigs(next); // optimistic — Reorder.Group already animated it
    const changed = next
      .map((c, index) => ({ c, index }))
      .filter(({ c, index }) => c.order_index !== index);
    if (changed.length === 0) return;

    setIsReordering(true);
    try {
      await Promise.all(
        changed.map(({ c, index }) =>
          apiClient.patch(`/admin/ai-configs/${c.id}`, { order_index: index })
        )
      );
      setConfigs((prev) => prev.map((c, index) => ({ ...c, order_index: index })));
    } catch (error: any) {
      toast.error(error.message || "Failed to save the new order.");
      loadConfigs();
    } finally {
      setIsReordering(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--color-background)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <BabyTiger size={36} expression="idle" />
        <div className="flex-1">
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">AI Models</h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Platform-default AI providers — these sit in every user's AI model bag alongside their
            own configs (see Settings). Drag to change what's tried first.
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-2xl mx-auto space-y-4"
        >
          {isLoading ? (
            <div className="flex flex-col items-center justify-center gap-4 py-16">
              <BabyTiger size={80} expression="thinking" />
              <p className="text-[var(--color-text-secondary)] text-sm">Loading platform AI models...</p>
            </div>
          ) : (
            <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-[var(--color-text-primary)] flex items-center gap-2">
                  <Server className="w-4 h-4" /> Platform defaults
                </h2>
                {isReordering && (
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-[var(--color-text-tertiary)]" />
                )}
              </div>

              {configs.length === 0 ? (
                <p className="text-xs text-[var(--color-text-tertiary)]">
                  No platform-default AI models configured yet — VengaiCode falls back to its
                  built-in Ollama/Groq settings until you add one here.
                </p>
              ) : (
                <Reorder.Group as="div" axis="y" values={configs} onReorder={handleReorder} className="space-y-2">
                  {configs.map((config, index) => (
                    <Reorder.Item
                      as="div"
                      key={config.id}
                      value={config}
                      className="rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-4 py-3 cursor-grab active:cursor-grabbing"
                    >
                      <div className="flex items-center gap-3">
                        <GripVertical className="w-4 h-4 text-[var(--color-text-tertiary)] flex-shrink-0" />
                        <span className="text-[10px] font-mono text-[var(--color-text-tertiary)] w-4 flex-shrink-0">
                          {index + 1}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">
                              {config.label}
                            </p>
                            {config.is_active ? (
                              <span className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-[var(--color-success-light)] text-[var(--color-success)] text-[10px] font-semibold">
                                <Check className="w-2.5 h-2.5" /> Active
                              </span>
                            ) : (
                              <span className="px-1.5 py-0.5 rounded-full bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)] text-[10px] font-semibold">
                                Paused
                              </span>
                            )}
                            {config.task_type && (
                              <span className="px-1.5 py-0.5 rounded-full bg-[var(--color-primary)]/10 text-[var(--color-primary)] text-[10px] font-semibold">
                                {config.task_type === "codegen" ? "Codegen only" : "Chat only"}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-[var(--color-text-tertiary)] truncate">
                            {PROVIDER_LABELS[config.provider_type]} · {config.model_name}
                            {config.has_api_key && " · key set"}
                          </p>
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0">
                          <button
                            onClick={() => handleToggleActive(config)}
                            className="px-2 py-1 rounded-lg text-xs font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)] transition-colors"
                          >
                            {config.is_active ? "Pause" : "Activate"}
                          </button>
                          <button
                            onClick={() => startEdit(config)}
                            className="px-2 py-1 rounded-lg text-xs font-medium text-[var(--color-primary)] hover:bg-[var(--color-surface-raised)] transition-colors"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleDelete(config)}
                            className="p-1.5 rounded-lg hover:bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)] hover:text-[var(--color-error)] transition-colors"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    </Reorder.Item>
                  ))}
                </Reorder.Group>
              )}

              {/* Add / edit form */}
              {showForm ? (
                <div className="space-y-3 pt-2 border-t border-[var(--color-border)]">
                  <div>
                    <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                      Provider
                    </label>
                    <select
                      value={form.provider_type}
                      disabled={!!editingId}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, provider_type: e.target.value as AdminProviderType }))
                      }
                      className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)] disabled:opacity-60"
                    >
                      {(Object.entries(PROVIDER_LABELS) as [AdminProviderType, string][]).map(
                        ([value, providerLabel]) => (
                          <option key={value} value={value}>
                            {providerLabel}
                          </option>
                        )
                      )}
                    </select>
                  </div>

                  {(form.provider_type === "custom" || form.provider_type === "ollama") && (
                    <div>
                      <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                        Base URL {form.provider_type === "custom" && "*"}
                      </label>
                      <input
                        value={form.base_url}
                        onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
                        placeholder={
                          form.provider_type === "ollama"
                            ? "Defaults to the backend's configured Ollama host"
                            : "https://your-endpoint.example.com/v1"
                        }
                        className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                      />
                    </div>
                  )}

                  {form.provider_type !== "ollama" && (
                    <div>
                      <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                        API key {editingId && "(leave blank to keep the current key)"}
                      </label>
                      <input
                        value={form.api_key}
                        onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                        type="password"
                        placeholder={editingId ? "••••••••" : "sk-..."}
                        className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                      />
                    </div>
                  )}

                  <div>
                    <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                      Model name *
                    </label>
                    <input
                      value={form.model_name}
                      onChange={(e) => setForm((f) => ({ ...f, model_name: e.target.value }))}
                      placeholder="e.g. openai/gpt-oss-120b, qwen2.5-coder"
                      className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                      Label *
                    </label>
                    <input
                      value={form.label}
                      onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))}
                      placeholder="e.g. Company Groq account"
                      className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                      Use for
                    </label>
                    <select
                      value={form.task_type}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, task_type: e.target.value as AdminTaskType | "" }))
                      }
                      className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                    >
                      <option value="">Any task (default)</option>
                      <option value="codegen">Code generation only</option>
                      <option value="general">Chat &amp; planning only</option>
                    </select>
                  </div>

                  <label className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                    <input
                      type="checkbox"
                      checked={form.is_active}
                      onChange={(e) => setForm((f) => ({ ...f, is_active: e.target.checked }))}
                      className="rounded border-[var(--color-border)]"
                    />
                    Included in every user's AI model bag
                  </label>

                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={handleSave}
                      disabled={isSaving}
                      className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-white text-sm font-semibold transition-all disabled:opacity-60"
                    >
                      {isSaving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                      {editingId ? "Save changes" : "Add platform default"}
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
                  onClick={() => {
                    setForm(EMPTY_FORM);
                    setShowForm(true);
                  }}
                  className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-primary)] hover:text-[var(--color-primary-hover)]"
                >
                  <Plus className="w-3.5 h-3.5" /> Add platform-default AI model
                </button>
              )}
            </div>
          )}

          <div className="flex items-start gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3">
            <ShieldCheck className="w-4 h-4 text-[var(--color-text-tertiary)] flex-shrink-0 mt-0.5" />
            <p className="text-xs text-[var(--color-text-tertiary)]">
              Every user can still bring their own AI model in Settings — those are always layered
              on top of these platform defaults, and each user can drag their own personal order.
            </p>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
