import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { router } from "expo-router";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Cpu,
  Frame,
  LogOut,
  Moon,
  Plus,
  Server,
  ShieldCheck,
  Sun,
  Trash2,
} from "lucide-react-native";

import ScreenContainer from "@/components/ui/ScreenContainer";
import { useToast } from "@/components/ui/Toast";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { logoutUser } from "@/store/slices/authSlice";
import { toggleTheme } from "@/store/slices/uiSlice";
import {
  AIProviderType,
  AIConfigTaskType,
  createAIConfig,
  deleteAIConfig,
  fetchAIBag,
  fetchAIConfigs,
  setActiveAIConfig,
  setAIBagOrder,
  useDefaultAI,
} from "@/store/slices/aiConfigSlice";
import { connectFigma, disconnectFigma, fetchFigmaStatus } from "@/store/slices/figmaSlice";
import { useTheme } from "@/theme/useTheme";

const PROVIDERS: { value: AIProviderType; label: string }[] = [
  { value: "groq", label: "Groq (own key)" },
  { value: "openai", label: "OpenAI (own key)" },
  { value: "anthropic", label: "Anthropic (own key)" },
  { value: "xai", label: "Grok / xAI (own key)" },
  { value: "custom", label: "Custom endpoint" },
];

const TASK_TYPES: { value: AIConfigTaskType | ""; label: string }[] = [
  { value: "", label: "Any task (default)" },
  { value: "codegen", label: "Code generation only" },
  { value: "general", label: "Chat & planning only" },
];

export default function SettingsScreen() {
  const dispatch = useAppDispatch();
  const { colors, theme } = useTheme();
  const { showToast } = useToast();
  const { user } = useAppSelector((state) => state.auth);
  const { configs, isSaving, bag, isBagSaving } = useAppSelector((state) => state.aiConfig);
  const { connected: figmaConnected, figmaHandle, isSaving: isFigmaSaving } = useAppSelector(
    (state) => state.figma
  );

  const [showForm, setShowForm] = useState(false);
  const [providerType, setProviderType] = useState<AIProviderType>("groq");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modelName, setModelName] = useState("");
  const [label, setLabel] = useState("");
  const [taskType, setTaskType] = useState<AIConfigTaskType | "">("");

  const [showFigmaForm, setShowFigmaForm] = useState(false);
  const [figmaToken, setFigmaToken] = useState("");

  useEffect(() => {
    dispatch(fetchAIConfigs());
    dispatch(fetchAIBag());
    dispatch(fetchFigmaStatus());
  }, [dispatch]);

  const activeConfig = configs.find((c) => c.is_active);
  const refreshBag = () => dispatch(fetchAIBag());

  const handleLogout = async () => {
    await dispatch(logoutUser());
    router.replace("/(auth)/login");
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
      showToast("Model name and a label are required.", "error");
      return;
    }
    if (providerType === "custom" && !baseUrl.trim()) {
      showToast("A base URL is required for a custom endpoint.", "error");
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
      showToast(`Now using "${result.payload.label}" 🐯`);
      resetForm();
      refreshBag();
    } else {
      showToast((result.payload as string) || "Failed to save AI model.", "error");
    }
  };

  const handleUseDefault = async () => {
    await dispatch(useDefaultAI(activeConfig?.id));
    showToast("Switched back to VengaiCode's default AI.");
    refreshBag();
  };

  const handleSetActive = async (id: string) => {
    const result = await dispatch(setActiveAIConfig(id));
    if (setActiveAIConfig.fulfilled.match(result)) {
      showToast(`Now using "${result.payload.label}" 🐯`);
      refreshBag();
    }
  };

  const handleDelete = async (id: string) => {
    await dispatch(deleteAIConfig(id));
    showToast("Removed.");
    refreshBag();
  };

  // ── AI model order (up/down reorder of the bag) ──
  const handleMoveBagItem = async (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= bag.length) return;
    const next = [...bag];
    [next[index], next[target]] = [next[target], next[index]];
    const result = await dispatch(setAIBagOrder(next.map((c) => c.id)));
    if (!setAIBagOrder.fulfilled.match(result)) {
      showToast((result.payload as string) || "Failed to save the new order.", "error");
    }
  };

  // ── Figma connection ──

  const handleConnectFigma = async () => {
    if (!figmaToken.trim()) {
      showToast("Paste your Figma personal access token first.", "error");
      return;
    }
    const result = await dispatch(connectFigma(figmaToken.trim()));
    if (connectFigma.fulfilled.match(result)) {
      showToast(`Connected to Figma as ${result.payload.figma_handle} 🐯`);
      setFigmaToken("");
      setShowFigmaForm(false);
    } else {
      showToast((result.payload as string) || "Failed to connect Figma account.", "error");
    }
  };

  const handleDisconnectFigma = async () => {
    await dispatch(disconnectFigma());
    showToast("Figma account disconnected.");
  };

  return (
    <ScreenContainer>
      <Text style={[styles.title, { color: colors.textPrimary }]}>Settings</Text>

      {user && (
        <View style={[styles.profileCard, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <View style={[styles.avatar, { backgroundColor: colors.primaryLight }]}>
            <Text style={{ color: colors.primary, fontWeight: "700", fontSize: 18 }}>
              {user.full_name.charAt(0).toUpperCase()}
            </Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={[styles.name, { color: colors.textPrimary }]}>{user.full_name}</Text>
            <Text style={[styles.tier, { color: colors.textTertiary }]}>{user.tier} tier</Text>
          </View>
        </View>
      )}

      <Pressable
        onPress={() => dispatch(toggleTheme())}
        style={[styles.row, { borderColor: colors.border, backgroundColor: colors.surface }]}
      >
        {theme === "dark" ? <Moon size={18} color={colors.textPrimary} /> : <Sun size={18} color={colors.textPrimary} />}
        <Text style={{ color: colors.textPrimary, fontSize: 14, flex: 1 }}>
          {theme === "dark" ? "Dark theme" : "Light theme"}
        </Text>
        <Text style={{ color: colors.textTertiary, fontSize: 12 }}>Tap to switch</Text>
      </Pressable>

      {/* ── AI Model section ── */}
      <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <View style={styles.sectionHeader}>
          <Cpu size={16} color={colors.textPrimary} />
          <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>AI Model</Text>
        </View>
        <Text style={[styles.sectionSubtitle, { color: colors.textTertiary }]}>
          Use VengaiCode's default AI, or bring your own — your own provider key or a
          self-hosted local model. Switching to your own never uses VengaiCode's AI quota.
        </Text>

        {/* Current status */}
        <View style={[styles.statusRow, { borderColor: colors.border, backgroundColor: colors.background }]}>
          <View style={{ flex: 1 }}>
            <Text style={[styles.statusLabel, { color: colors.textTertiary }]}>Currently using</Text>
            <Text style={[styles.statusValue, { color: colors.textPrimary }]}>
              {activeConfig ? activeConfig.label : "VengaiCode default (Ollama + Groq)"}
            </Text>
          </View>
          {activeConfig && (
            <Pressable onPress={handleUseDefault}>
              <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "600" }}>Switch to default</Text>
            </Pressable>
          )}
        </View>

        {/* Saved configs */}
        {configs.map((config) => (
          <View
            key={config.id}
            style={[styles.configRow, { borderColor: colors.border }]}
          >
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Text style={[styles.configLabel, { color: colors.textPrimary }]} numberOfLines={1}>
                  {config.label}
                </Text>
                {config.is_active && (
                  <View style={[styles.activeBadge, { backgroundColor: colors.primaryLight }]}>
                    <Check size={10} color={colors.primary} />
                    <Text style={{ color: colors.primary, fontSize: 10, fontWeight: "700" }}>Active</Text>
                  </View>
                )}
              </View>
              <Text style={[styles.configMeta, { color: colors.textTertiary }]} numberOfLines={1}>
                {config.provider_type} · {config.model_name}
              </Text>
            </View>
            {!config.is_active && (
              <Pressable onPress={() => handleSetActive(config.id)} style={{ marginRight: 12 }}>
                <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "600" }}>Use this</Text>
              </Pressable>
            )}
            <Pressable onPress={() => handleDelete(config.id)} hitSlop={8}>
              <Trash2 size={16} color={colors.textTertiary} />
            </Pressable>
          </View>
        ))}

        {/* AI model order — the effective fallback chain: own configs plus
            VengaiCode's platform defaults (Ollama, Groq), all in one list.
            Whatever's on top is tried first. */}
        {bag.length > 0 && (
          <View style={{ gap: 6, marginTop: 4 }}>
            <Text style={[styles.hint, { color: colors.textTertiary }]}>
              AI model order — what's tried first is on top.
            </Text>
            {bag.map((entry, index) => (
              <View key={entry.id} style={[styles.bagRow, { borderColor: colors.border, backgroundColor: colors.background }]}>
                <Text style={{ color: colors.textTertiary, fontSize: 10, fontFamily: "monospace", width: 16 }}>
                  {index + 1}
                </Text>
                {entry.is_platform_default ? (
                  <Server size={13} color={colors.textTertiary} />
                ) : (
                  <Cpu size={13} color={colors.primary} />
                )}
                <View style={{ flex: 1 }}>
                  <Text style={[styles.configLabel, { color: colors.textPrimary, fontSize: 12 }]} numberOfLines={1}>
                    {entry.label}
                  </Text>
                  <Text style={{ color: colors.textTertiary, fontSize: 10 }}>
                    {entry.is_platform_default ? "VengaiCode default" : "Your config"}
                    {entry.task_type ? ` · ${entry.task_type === "codegen" ? "Codegen only" : "Chat only"}` : ""}
                  </Text>
                </View>
                <View style={{ flexDirection: "row", gap: 2 }}>
                  <Pressable
                    onPress={() => handleMoveBagItem(index, -1)}
                    disabled={index === 0 || isBagSaving}
                    hitSlop={8}
                    style={{ opacity: index === 0 ? 0.3 : 1, padding: 4 }}
                  >
                    <ChevronUp size={16} color={colors.textSecondary} />
                  </Pressable>
                  <Pressable
                    onPress={() => handleMoveBagItem(index, 1)}
                    disabled={index === bag.length - 1 || isBagSaving}
                    hitSlop={8}
                    style={{ opacity: index === bag.length - 1 ? 0.3 : 1, padding: 4 }}
                  >
                    <ChevronDown size={16} color={colors.textSecondary} />
                  </Pressable>
                </View>
              </View>
            ))}
          </View>
        )}

        {/* Add form */}
        {showForm ? (
          <View style={[styles.formArea, { borderColor: colors.border }]}>
            <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>Provider</Text>
            <View style={styles.chipRow}>
              {PROVIDERS.map((p) => {
                const selected = providerType === p.value;
                return (
                  <Pressable
                    key={p.value}
                    onPress={() => setProviderType(p.value)}
                    style={[
                      styles.chip,
                      {
                        borderColor: selected ? colors.primary : colors.border,
                        backgroundColor: selected ? colors.primaryLight : colors.background,
                      },
                    ]}
                  >
                    <Text style={{ color: selected ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>
                      {p.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            {providerType === "custom" && (
              <>
                <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>Base URL *</Text>
                <TextInput
                  value={baseUrl}
                  onChangeText={setBaseUrl}
                  placeholder="http://192.168.1.5:10086/v1"
                  placeholderTextColor={colors.textTertiary}
                  autoCapitalize="none"
                  style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
                />
                <Text style={[styles.hint, { color: colors.textTertiary }]}>
                  Tip: on a phone, "127.0.0.1" means this phone, not your computer. Use your
                  computer's network IP (e.g. 192.168.x.x) if the model runs there, and make
                  sure your phone is on the same Wi-Fi.
                </Text>
              </>
            )}

            <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>
              API key {providerType === "custom" && "(optional)"}
            </Text>
            <TextInput
              value={apiKey}
              onChangeText={setApiKey}
              placeholder={providerType === "custom" ? "Leave blank if not required" : "sk-..."}
              placeholderTextColor={colors.textTertiary}
              secureTextEntry
              autoCapitalize="none"
              style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
            />

            <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>Model name *</Text>
            <TextInput
              value={modelName}
              onChangeText={setModelName}
              placeholder="e.g. llama3-70b-8192"
              placeholderTextColor={colors.textTertiary}
              autoCapitalize="none"
              style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
            />

            <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>Label *</Text>
            <TextInput
              value={label}
              onChangeText={setLabel}
              placeholder="e.g. My local Qwen (USB)"
              placeholderTextColor={colors.textTertiary}
              style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
            />

            <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>Use for</Text>
            <View style={styles.chipRow}>
              {TASK_TYPES.map((t) => {
                const selected = taskType === t.value;
                return (
                  <Pressable
                    key={t.value || "any"}
                    onPress={() => setTaskType(t.value)}
                    style={[
                      styles.chip,
                      {
                        borderColor: selected ? colors.primary : colors.border,
                        backgroundColor: selected ? colors.primaryLight : colors.background,
                      },
                    ]}
                  >
                    <Text style={{ color: selected ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>
                      {t.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>

            <View style={{ flexDirection: "row", gap: 10, marginTop: 4 }}>
              <Pressable
                onPress={handleSave}
                disabled={isSaving}
                style={[styles.saveButton, { backgroundColor: colors.primary, opacity: isSaving ? 0.6 : 1 }]}
              >
                <Text style={{ color: "#fff", fontWeight: "700", fontSize: 13 }}>Save & use this model</Text>
              </Pressable>
              <Pressable onPress={resetForm} style={[styles.cancelButton, { borderColor: colors.border }]}>
                <Text style={{ color: colors.textSecondary, fontSize: 13, fontWeight: "600" }}>Cancel</Text>
              </Pressable>
            </View>
          </View>
        ) : (
          <Pressable onPress={() => setShowForm(true)} style={styles.addRow}>
            <Plus size={14} color={colors.primary} />
            <Text style={{ color: colors.primary, fontSize: 13, fontWeight: "600" }}>Add AI model configuration</Text>
          </Pressable>
        )}
      </View>

      {/* ── Figma section ── */}
      <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <View style={styles.sectionHeader}>
          <Frame size={16} color={colors.textPrimary} />
          <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>Figma</Text>
        </View>
        <Text style={[styles.sectionSubtitle, { color: colors.textTertiary }]}>
          Connect your Figma account to import a frame straight into the UI/UX phase — Baby Tiger
          converts it into editable HTML/CSS, same as an uploaded mockup. Uses a free Figma
          personal access token, no paid plan needed.
        </Text>

        {figmaConnected ? (
          <View style={[styles.statusRow, { borderColor: colors.border, backgroundColor: colors.background }]}>
            <View style={{ flex: 1 }}>
              <Text style={[styles.statusLabel, { color: colors.textTertiary }]}>Connected as</Text>
              <Text style={[styles.statusValue, { color: colors.textPrimary }]}>{figmaHandle}</Text>
            </View>
            <Pressable onPress={handleDisconnectFigma}>
              <Text style={{ color: colors.error, fontSize: 12, fontWeight: "600" }}>Disconnect</Text>
            </Pressable>
          </View>
        ) : showFigmaForm ? (
          <View style={[styles.formArea, { borderColor: colors.border }]}>
            <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>Personal access token *</Text>
            <TextInput
              value={figmaToken}
              onChangeText={setFigmaToken}
              placeholder="figd_..."
              placeholderTextColor={colors.textTertiary}
              secureTextEntry
              autoCapitalize="none"
              style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
            />
            <Text style={[styles.hint, { color: colors.textTertiary }]}>
              Generate one free in Figma: Settings → Personal access tokens.
            </Text>

            <View style={{ flexDirection: "row", gap: 10, marginTop: 4 }}>
              <Pressable
                onPress={handleConnectFigma}
                disabled={isFigmaSaving}
                style={[styles.saveButton, { backgroundColor: colors.primary, opacity: isFigmaSaving ? 0.6 : 1 }]}
              >
                <Text style={{ color: "#fff", fontWeight: "700", fontSize: 13 }}>Connect</Text>
              </Pressable>
              <Pressable
                onPress={() => {
                  setShowFigmaForm(false);
                  setFigmaToken("");
                }}
                style={[styles.cancelButton, { borderColor: colors.border }]}
              >
                <Text style={{ color: colors.textSecondary, fontSize: 13, fontWeight: "600" }}>Cancel</Text>
              </Pressable>
            </View>
          </View>
        ) : (
          <Pressable onPress={() => setShowFigmaForm(true)} style={styles.addRow}>
            <Plus size={14} color={colors.primary} />
            <Text style={{ color: colors.primary, fontSize: 13, fontWeight: "600" }}>Connect Figma account</Text>
          </Pressable>
        )}
      </View>

      {user?.is_admin && (
        <Pressable
          onPress={() => router.push("/(app)/admin" as any)}
          style={[styles.row, { borderColor: colors.border, backgroundColor: colors.surface }]}
        >
          <ShieldCheck size={18} color={colors.primary} />
          <Text style={{ color: colors.textPrimary, fontSize: 14, flex: 1, fontWeight: "600" }}>Admin</Text>
        </Pressable>
      )}

      {user?.is_admin && (
        <Pressable
          onPress={() => router.push("/(app)/admin/ai-models" as any)}
          style={[styles.row, { borderColor: colors.border, backgroundColor: colors.surface }]}
        >
          <Server size={18} color={colors.primary} />
          <Text style={{ color: colors.textPrimary, fontSize: 14, flex: 1, fontWeight: "600" }}>AI Models</Text>
        </Pressable>
      )}

      <Pressable onPress={handleLogout} style={[styles.row, { borderColor: colors.error, backgroundColor: colors.surface }]}>
        <LogOut size={18} color={colors.error} />
        <Text style={{ color: colors.error, fontSize: 14, fontWeight: "600" }}>Logout</Text>
      </Pressable>
    </ScreenContainer>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 22, fontWeight: "700", marginBottom: 20 },
  profileCard: { flexDirection: "row", alignItems: "center", gap: 12, borderWidth: 1, borderRadius: 14, padding: 14, marginBottom: 16 },
  avatar: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  name: { fontSize: 15, fontWeight: "700" },
  tier: { fontSize: 12, textTransform: "capitalize" },
  row: { flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderRadius: 12, padding: 14, marginBottom: 12 },
  card: { borderWidth: 1, borderRadius: 14, padding: 16, marginBottom: 16, gap: 10 },
  sectionHeader: { flexDirection: "row", alignItems: "center", gap: 6 },
  sectionTitle: { fontSize: 14, fontWeight: "700" },
  sectionSubtitle: { fontSize: 12, lineHeight: 17 },
  statusRow: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderRadius: 12, padding: 12 },
  statusLabel: { fontSize: 11 },
  statusValue: { fontSize: 14, fontWeight: "600" },
  configRow: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderRadius: 12, padding: 12 },
  configLabel: { fontSize: 13, fontWeight: "600", flexShrink: 1 },
  configMeta: { fontSize: 11, marginTop: 2 },
  activeBadge: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999 },
  bagRow: { flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1, borderRadius: 10, padding: 10 },
  formArea: { borderTopWidth: 1, paddingTop: 12, gap: 6 },
  fieldLabel: { fontSize: 12, fontWeight: "600", marginTop: 6 },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 13 },
  hint: { fontSize: 11, lineHeight: 15, marginTop: 2 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 8 },
  saveButton: { flex: 1, borderRadius: 10, paddingVertical: 12, alignItems: "center" },
  cancelButton: { borderWidth: 1, borderRadius: 10, paddingVertical: 12, paddingHorizontal: 16, alignItems: "center" },
  addRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  comingSoonCard: { borderWidth: 1, borderRadius: 12, padding: 20, marginBottom: 12, alignItems: "center" },
});
