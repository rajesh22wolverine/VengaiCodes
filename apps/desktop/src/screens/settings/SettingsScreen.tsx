import { useEffect, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { motion, Reorder } from "framer-motion";
import {
  AlertTriangle,
  Check,
  Cpu,
  Figma,
  GripVertical,
  HardDrive,
  Loader2,
  Plus,
  Radar,
  Server,
  Sparkles,
  Trash2,
  Usb,
} from "lucide-react";
import toast from "react-hot-toast";
import { invoke } from "@tauri-apps/api/tauri";

import { AppDispatch, RootState } from "@/store";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import { IS_LOCAL_BACKEND } from "@/lib/api";
import { buildPortableLabel } from "@/lib/portableLabel";
import {
  AIProviderType,
  AIConfigTaskType,
  BagConfig,
  createAIConfig,
  deleteAIConfig,
  fetchAIBag,
  fetchAIConfigs,
  setActiveAIConfig,
  setAIBagOrder,
  useDefaultAI,
} from "@/store/slices/aiConfigSlice";
import { connectFigma, disconnectFigma, fetchFigmaStatus } from "@/store/slices/figmaSlice";

const PROVIDER_LABELS: Record<AIProviderType, string> = {
  groq: "Groq (your own key)",
  openai: "OpenAI (your own key)",
  anthropic: "Anthropic Claude (your own key)",
  xai: "Grok / xAI (your own key)",
  custom: "Custom endpoint (self-hosted / local)",
  portable: "Portable AI model (USB)",
};

// Fixed local ports the bundled portable-engine sidecar can run on — one
// per fallback-chain slot, so up to 3 portable models can be configured.
const PORTABLE_ENGINE_PORTS = [11501, 11502, 11503];

// Rust command return shapes — see apps/desktop/src-tauri/src/commands/{scan,ai}.rs.
// Tauri serializes these with serde's default (snake_case) field names.
interface DriveInfo {
  mount_point: string;
  name: string;
  available_space: number;
  total_space: number;
}
interface PortableModelInfo {
  path: string;
  filename: string;
  size_bytes: number;
  display_name: string;
}
interface PortableEngineStatus {
  port: number;
  base_url: string;
  ready: boolean;
}

// Uncensored AI Studio's local llama.cpp server — the verified "USB pendrive
// AI model" case this button is built for. Always available at /health.
const LOCAL_STUDIO_URL = "http://127.0.0.1:10086";

export default function SettingsScreen() {
  const dispatch = useDispatch<AppDispatch>();
  const { configs, isLoading, isSaving, bag, isBagSaving } = useSelector(
    (state: RootState) => state.aiConfig
  );
  const {
    connected: figmaConnected,
    figmaHandle,
    isLoading: isFigmaLoading,
    isSaving: isFigmaSaving,
  } = useSelector((state: RootState) => state.figma);

  const [showForm, setShowForm] = useState(false);
  const [showFigmaForm, setShowFigmaForm] = useState(false);
  const [figmaToken, setFigmaToken] = useState("");
  const [isDetecting, setIsDetecting] = useState(false);
  const [providerType, setProviderType] = useState<AIProviderType>("groq");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modelName, setModelName] = useState("");
  const [label, setLabel] = useState("");
  const [taskType, setTaskType] = useState<AIConfigTaskType | "">("");

  const [isScanningDrives, setIsScanningDrives] = useState(false);
  const [foundModels, setFoundModels] = useState<PortableModelInfo[]>([]);
  const [launchingModelPath, setLaunchingModelPath] = useState<string | null>(null);

  // Local, immediately-reorderable copy of the bag — Reorder.Group needs to
  // mutate order on every drag frame, well before the PUT round-trip that
  // persists it lands and refreshes Redux state.
  const [bagOrder, setBagOrder] = useState<BagConfig[]>([]);

  useEffect(() => {
    dispatch(fetchAIConfigs());
    dispatch(fetchAIBag());
    dispatch(fetchFigmaStatus());
  }, [dispatch]);

  useEffect(() => {
    setBagOrder(bag);
  }, [bag]);

  const activeConfig = configs.find((c) => c.is_active);

  const refreshBag = () => {
    dispatch(fetchAIBag());
  };

  const resetForm = () => {
    setProviderType("groq");
    setBaseUrl("");
    setApiKey("");
    setModelName("");
    setLabel("");
    setTaskType("");
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
        task_type: taskType || undefined,
      })
    );

    if (createAIConfig.fulfilled.match(result)) {
      toast.success(`Now using "${result.payload.label}" 🐯`);
      resetForm();
      refreshBag();
    } else {
      toast.error((result.payload as string) || "Failed to save AI model.");
    }
  };

  const handleUseDefault = async () => {
    await dispatch(useDefaultAI(activeConfig?.id));
    toast.success("Switched back to VengaiCode's default AI.");
    refreshBag();
  };

  const handleSetActive = async (id: string) => {
    const result = await dispatch(setActiveAIConfig(id));
    if (setActiveAIConfig.fulfilled.match(result)) {
      toast.success(`Now using "${result.payload.label}" 🐯`);
      refreshBag();
    }
  };

  const handleDelete = async (id: string) => {
    await dispatch(deleteAIConfig(id));
    toast.success("Removed.");
    refreshBag();
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

  // ── Portable AI model (USB drive) — detect and launch ──

  const detectPortableModel = async () => {
    setIsScanningDrives(true);
    setFoundModels([]);
    try {
      const drives = await invoke<DriveInfo[]>("list_removable_drives");
      if (drives.length === 0) {
        toast.error("No USB/removable drive detected. Plug one in and try again.");
        return;
      }

      const perDrive = await Promise.all(
        drives.map((d) =>
          invoke<PortableModelInfo[]>("scan_drive_for_models", { path: d.mount_point })
        )
      );
      const models = perDrive.flat();

      if (models.length === 0) {
        toast.error("No AI model files found on the connected drive(s).");
        return;
      }
      setFoundModels(models);
      toast.success(`Found ${models.length} AI model file${models.length > 1 ? "s" : ""} 🐯`);
    } catch (error: any) {
      toast.error(error?.toString?.() || "Failed to scan for portable AI models.");
    } finally {
      setIsScanningDrives(false);
    }
  };

  const nextPortablePort = () => {
    const usedPorts = new Set(
      configs
        .filter((c) => c.provider_type === "portable")
        .map((c) => Number(c.base_url.match(/:(\d+)\//)?.[1]))
    );
    return PORTABLE_ENGINE_PORTS.find((p) => !usedPorts.has(p)) ?? PORTABLE_ENGINE_PORTS[0];
  };

  const handleAddPortableModel = async (model: PortableModelInfo) => {
    setLaunchingModelPath(model.path);
    try {
      const engine = await invoke<PortableEngineStatus>("launch_portable_model", {
        modelPath: model.path,
        port: nextPortablePort(),
      });
      setFoundModels((prev) => prev.filter((m) => m.path !== model.path));

      const result = await dispatch(
        createAIConfig({
          provider_type: "portable",
          base_url: engine.base_url,
          model_name: model.display_name,
          label: buildPortableLabel(model.display_name),
          is_active: configs.length === 0,
        })
      );

      if (createAIConfig.fulfilled.match(result)) {
        toast.success(`"${model.display_name}" added 🐯 Drag it into place below to set its order.`);
        refreshBag();
      } else {
        toast.error((result.payload as string) || "Failed to save the portable AI model.");
      }
    } catch (error: any) {
      toast.error(error?.toString?.() || "Failed to start the portable AI model.");
    } finally {
      setLaunchingModelPath(null);
    }
  };

  // ── AI model order (drag-to-reorder bag) ──

  const handleBagReorder = async (next: BagConfig[]) => {
    setBagOrder(next); // optimistic — Reorder.Group already animated it
    const result = await dispatch(setAIBagOrder(next.map((c) => c.id)));
    if (!setAIBagOrder.fulfilled.match(result)) {
      toast.error((result.payload as string) || "Failed to save the new order.");
      refreshBag();
    }
  };

  // ── Figma connection ──

  const handleConnectFigma = async () => {
    if (!figmaToken.trim()) {
      toast.error("Paste your Figma personal access token first.");
      return;
    }
    const result = await dispatch(connectFigma(figmaToken.trim()));
    if (connectFigma.fulfilled.match(result)) {
      toast.success(`Connected to Figma as ${result.payload.figma_handle} 🐯`);
      setFigmaToken("");
      setShowFigmaForm(false);
    } else {
      toast.error((result.payload as string) || "Failed to connect Figma account.");
    }
  };

  const handleDisconnectFigma = async () => {
    await dispatch(disconnectFigma());
    toast.success("Figma account disconnected.");
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
              <div className="flex-shrink-0 flex items-center gap-2">
                <button
                  onClick={detectLocalModel}
                  disabled={isDetecting}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-primary)] hover:text-[var(--color-primary)] transition-colors disabled:opacity-60"
                >
                  {isDetecting ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Radar className="w-3.5 h-3.5" />
                  )}
                  Detect local AI model
                </button>
                <button
                  onClick={detectPortableModel}
                  disabled={isScanningDrives}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-xs font-medium text-[var(--color-text-secondary)] hover:border-[var(--color-primary)] hover:text-[var(--color-primary)] transition-colors disabled:opacity-60"
                >
                  {isScanningDrives ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Usb className="w-3.5 h-3.5" />
                  )}
                  Detect Portable AI Model
                </button>
              </div>
            </div>

            {/* Local/portable models are launched on this machine and saved
                with a 127.0.0.1 base_url — only a backend also running on
                this machine can ever reach that. Warn rather than let
                someone on the hosted backend configure something that will
                always fail with a confusing connection error later. */}
            {!IS_LOCAL_BACKEND && (
              <div className="flex items-start gap-2 rounded-xl border border-[var(--color-warning)] bg-[var(--color-warning-light)] px-3 py-2.5">
                <AlertTriangle className="w-3.5 h-3.5 text-[var(--color-warning)] flex-shrink-0 mt-0.5" />
                <p className="text-xs text-[var(--color-text-secondary)]">
                  You're connected to VengaiCode's hosted backend, which can't reach a local or
                  portable AI model running on this machine. Local/portable models only work when
                  you're also running the VengaiCode backend locally on this same PC.
                </p>
              </div>
            )}

            {/* Portable model found on a USB drive — launch & save */}
            {foundModels.length > 0 && (
              <div className="space-y-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] p-3">
                <p className="text-xs font-medium text-[var(--color-text-secondary)] flex items-center gap-1.5">
                  <HardDrive className="w-3.5 h-3.5" /> Found on your USB drive
                </p>
                {foundModels.map((model) => (
                  <div
                    key={model.path}
                    className="flex items-center justify-between gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">
                        {model.display_name}
                      </p>
                      <p className="text-xs text-[var(--color-text-tertiary)] truncate">
                        {model.filename} · {(model.size_bytes / (1024 * 1024 * 1024)).toFixed(1)} GB
                      </p>
                    </div>
                    <button
                      onClick={() => handleAddPortableModel(model)}
                      disabled={launchingModelPath !== null}
                      className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60"
                    >
                      {launchingModelPath === model.path ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Sparkles className="w-3.5 h-3.5" />
                      )}
                      Add portable AI model
                    </button>
                  </div>
                ))}
              </div>
            )}

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

            {/* AI model order — drag to reorder the effective fallback chain:
                own configs plus VengaiCode's platform defaults (Ollama, Groq),
                all in one list. Whatever's on top is tried first. */}
            {bagOrder.length > 0 && (
              <div className="space-y-2 pt-2 border-t border-[var(--color-border)]">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-[var(--color-text-secondary)]">
                    AI model order — drag to change what's tried first
                  </p>
                  {isBagSaving && <Loader2 className="w-3 h-3 animate-spin text-[var(--color-text-tertiary)]" />}
                </div>
                <Reorder.Group
                  as="div"
                  axis="y"
                  values={bagOrder}
                  onReorder={handleBagReorder}
                  className="space-y-1.5"
                >
                  {bagOrder.map((entry, index) => (
                    <Reorder.Item
                      as="div"
                      key={entry.id}
                      value={entry}
                      className="flex items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 cursor-grab active:cursor-grabbing"
                    >
                      <GripVertical className="w-3.5 h-3.5 text-[var(--color-text-tertiary)] flex-shrink-0" />
                      <span className="text-[10px] font-mono text-[var(--color-text-tertiary)] w-4 flex-shrink-0">
                        {index + 1}
                      </span>
                      {entry.is_platform_default ? (
                        <Server className="w-3.5 h-3.5 text-[var(--color-text-tertiary)] flex-shrink-0" />
                      ) : (
                        <Cpu className="w-3.5 h-3.5 text-[var(--color-primary)] flex-shrink-0" />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium text-[var(--color-text-primary)] truncate">
                          {entry.label}
                        </p>
                      </div>
                      {entry.task_type && (
                        <span className="flex-shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-[var(--color-primary)]/10 text-[var(--color-primary)]">
                          {entry.task_type === "codegen" ? "Codegen only" : "Chat only"}
                        </span>
                      )}
                      <span className="flex-shrink-0 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)]">
                        {entry.is_platform_default ? "VengaiCode default" : "Your config"}
                      </span>
                    </Reorder.Item>
                  ))}
                </Reorder.Group>
              </div>
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
                    placeholder="e.g. openai/gpt-oss-120b, grok-4, or whatever's currently loaded locally"
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

                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                    Use for
                  </label>
                  <select
                    value={taskType}
                    onChange={(e) => setTaskType(e.target.value as AIConfigTaskType | "")}
                    className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                  >
                    <option value="">Any task (default)</option>
                    <option value="codegen">Code generation only</option>
                    <option value="general">Chat &amp; planning only</option>
                  </select>
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

          {/* ── Figma section ── */}
          <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-[var(--color-text-primary)] flex items-center gap-2">
                <Figma className="w-4 h-4" /> Figma
              </h2>
              <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
                Connect your Figma account to import a frame straight into the UI/UX phase — Baby
                Tiger converts it into editable HTML/CSS, same as an uploaded mockup. Uses a free
                Figma personal access token, no paid plan needed.
              </p>
            </div>

            {isFigmaLoading ? (
              <div className="flex justify-center py-2">
                <Loader2 className="w-5 h-5 animate-spin text-[var(--color-text-tertiary)]" />
              </div>
            ) : figmaConnected ? (
              <div className="flex items-center justify-between rounded-xl bg-[var(--color-background)] border border-[var(--color-border)] px-4 py-3">
                <div>
                  <p className="text-xs text-[var(--color-text-tertiary)]">Connected as</p>
                  <p className="text-sm font-medium text-[var(--color-text-primary)]">{figmaHandle}</p>
                </div>
                <button
                  onClick={handleDisconnectFigma}
                  className="text-xs font-medium text-[var(--color-error)] hover:opacity-80"
                >
                  Disconnect
                </button>
              </div>
            ) : showFigmaForm ? (
              <div className="space-y-3 pt-2 border-t border-[var(--color-border)]">
                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                    Personal access token *
                  </label>
                  <input
                    value={figmaToken}
                    onChange={(e) => setFigmaToken(e.target.value)}
                    type="password"
                    placeholder="figd_..."
                    className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                  />
                  <p className="text-xs text-[var(--color-text-tertiary)] mt-1.5">
                    Generate one free in Figma: Settings → Personal access tokens.
                  </p>
                </div>
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={handleConnectFigma}
                    disabled={isFigmaSaving}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-white text-sm font-semibold transition-all disabled:opacity-60"
                  >
                    {isFigmaSaving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    Connect
                  </button>
                  <button
                    onClick={() => {
                      setShowFigmaForm(false);
                      setFigmaToken("");
                    }}
                    className="px-4 py-2 rounded-xl border border-[var(--color-border)] text-sm font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)] transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setShowFigmaForm(true)}
                className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-primary)] hover:text-[var(--color-primary-hover)]"
              >
                <Plus className="w-3.5 h-3.5" /> Connect Figma account
              </button>
            )}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
