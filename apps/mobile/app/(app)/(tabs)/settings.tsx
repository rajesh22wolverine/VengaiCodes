import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { router } from "expo-router";
import { Check, Cpu, LogOut, Moon, Plus, Sun, Trash2 } from "lucide-react-native";

import ScreenContainer from "@/components/ui/ScreenContainer";
import { useToast } from "@/components/ui/Toast";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { logoutUser } from "@/store/slices/authSlice";
import { toggleTheme } from "@/store/slices/uiSlice";
import {
  AIConfigPriority,
  AIProviderType,
  createAIConfig,
  deleteAIConfig,
  fetchAIConfigs,
  setActiveAIConfig,
  setConfigPriority,
  useDefaultAI,
} from "@/store/slices/aiConfigSlice";
import { useTheme } from "@/theme/useTheme";

const PROVIDERS: { value: AIProviderType; label: string }[] = [
  { value: "groq", label: "Groq (own key)" },
  { value: "openai", label: "OpenAI (own key)" },
  { value: "anthropic", label: "Anthropic (own key)" },
  { value: "custom", label: "Custom endpoint" },
];

const PRIORITY_TIERS: { value: AIConfigPriority; label: string }[] = [
  { value: "primary", label: "Primary" },
  { value: "secondary", label: "Secondary" },
  { value: "tertiary", label: "Tertiary" },
];

export default function SettingsScreen() {
  const dispatch = useAppDispatch();
  const { colors, theme } = useTheme();
  const { showToast } = useToast();
  const { user } = useAppSelector((state) => state.auth);
  const { configs, isSaving } = useAppSelector((state) => state.aiConfig);

  const [showForm, setShowForm] = useState(false);
  const [providerType, setProviderType] = useState<AIProviderType>("groq");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [modelName, setModelName] = useState("");
  const [label, setLabel] = useState("");

  useEffect(() => {
    dispatch(fetchAIConfigs());
  }, [dispatch]);

  const activeConfig = configs.find((c) => c.is_active);

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
      })
    );

    if (createAIConfig.fulfilled.match(result)) {
      showToast(`Now using "${result.payload.label}" 🐯`);
      resetForm();
    } else {
      showToast((result.payload as string) || "Failed to save AI model.", "error");
    }
  };

  const handleUseDefault = async () => {
    await dispatch(useDefaultAI(activeConfig?.id));
    showToast("Switched back to VengaiCode's default AI.");
  };

  const handleSetActive = async (id: string) => {
    const result = await dispatch(setActiveAIConfig(id));
    if (setActiveAIConfig.fulfilled.match(result)) {
      showToast(`Now using "${result.payload.label}" 🐯`);
    }
  };

  const handleDelete = async (id: string) => {
    await dispatch(deleteAIConfig(id));
    showToast("Removed.");
  };

  const handleChangePriority = async (id: string, priority: AIConfigPriority | null, current: AIConfigPriority | null) => {
    const next = current === priority ? null : priority;
    const result = await dispatch(setConfigPriority({ id, priority: next }));
    if (setConfigPriority.fulfilled.match(result)) {
      showToast(next ? `Set as ${next.charAt(0).toUpperCase() + next.slice(1)}.` : "Removed from fallback order.");
    }
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
        {configs.length > 0 && (
          <Text style={[styles.hint, { color: colors.textTertiary }]}>
            Optionally rank your own models — if Primary fails, the app automatically tries
            Secondary, then Tertiary.
          </Text>
        )}
        {configs.map((config) => (
          <View
            key={config.id}
            style={[styles.configRow, { borderColor: colors.border, flexDirection: "column", alignItems: "stretch", gap: 8 }]}
          >
            <View style={{ flexDirection: "row", alignItems: "center" }}>
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
                  {config.priority && (
                    <View style={[styles.activeBadge, { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border }]}>
                      <Text style={{ color: colors.textSecondary, fontSize: 10, fontWeight: "700" }}>
                        {config.priority.charAt(0).toUpperCase() + config.priority.slice(1)}
                      </Text>
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
            <View style={styles.chipRow}>
              {PRIORITY_TIERS.map((tier) => {
                const selected = config.priority === tier.value;
                return (
                  <Pressable
                    key={tier.value}
                    onPress={() => handleChangePriority(config.id, tier.value, config.priority)}
                    style={[
                      styles.chip,
                      {
                        borderColor: selected ? colors.primary : colors.border,
                        backgroundColor: selected ? colors.primaryLight : colors.background,
                      },
                    ]}
                  >
                    <Text style={{ color: selected ? colors.primary : colors.textSecondary, fontSize: 11, fontWeight: "600" }}>
                      {tier.label}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
        ))}

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
