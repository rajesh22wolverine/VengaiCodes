import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from "react-native";
import { Redirect } from "expo-router";
import { Check, ChevronDown, ChevronUp, Plus, Server, Trash2 } from "lucide-react-native";

import apiClient from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import { useAppSelector } from "@/store/hooks";
import { useTheme } from "@/theme/useTheme";

// ─── Platform-default AI config (user_id IS NULL) — mirrors backend
// AdminAIConfigResponse. Sits in every user's AI model bag alongside
// their own BYO configs — see app/ai/orchestrator.get_effective_bag(). ───
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
}

const PROVIDERS: { value: AdminProviderType; label: string }[] = [
  { value: "groq", label: "Groq" },
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic Claude" },
  { value: "xai", label: "Grok / xAI" },
  { value: "ollama", label: "Ollama (local/self-hosted)" },
  { value: "custom", label: "Custom endpoint" },
];

const PROVIDERS_REQUIRING_KEY = new Set<AdminProviderType>(["groq", "openai", "anthropic", "xai"]);

const TASK_TYPES: { value: AdminTaskType | ""; label: string }[] = [
  { value: "", label: "Any task (default)" },
  { value: "codegen", label: "Code generation only" },
  { value: "general", label: "Chat & planning only" },
];

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
  const { colors } = useTheme();
  const { showToast } = useToast();
  const isAdmin = useAppSelector((state) => state.auth.user?.is_admin);

  const [configs, setConfigs] = useState<PlatformAIConfig[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);

  const loadConfigs = async () => {
    setIsLoading(true);
    try {
      const { data } = await apiClient.get("/admin/ai-configs");
      setConfigs(data.configs || []);
    } catch (error: any) {
      showToast(error.message || "Failed to load platform AI models.", "error");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadConfigs();
  }, []);

  if (!isAdmin) return <Redirect href="/(app)/(tabs)/home" />;

  const resetForm = () => {
    setForm(EMPTY_FORM);
    setShowForm(false);
  };

  const handleSave = async () => {
    if (!form.model_name.trim() || !form.label.trim()) {
      showToast("Model name and a label are required.", "error");
      return;
    }
    if (form.provider_type === "custom" && !form.base_url.trim()) {
      showToast("A base URL is required for a custom endpoint.", "error");
      return;
    }
    if (PROVIDERS_REQUIRING_KEY.has(form.provider_type) && !form.api_key.trim()) {
      showToast(`An API key is required for this provider.`, "error");
      return;
    }

    setIsSaving(true);
    try {
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
      showToast(`"${data.config.label}" added to every user's AI model bag 🐯`);
      resetForm();
    } catch (error: any) {
      showToast(error.message || "Failed to save.", "error");
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
      showToast(error.message || "Failed to update.", "error");
    }
  };

  const handleDelete = async (config: PlatformAIConfig) => {
    try {
      await apiClient.delete(`/admin/ai-configs/${config.id}`);
      setConfigs((prev) => prev.filter((c) => c.id !== config.id));
      showToast("Removed.");
    } catch (error: any) {
      showToast(error.message || "Failed to delete.", "error");
    }
  };

  const handleMove = async (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= configs.length) return;
    const next = [...configs];
    [next[index], next[target]] = [next[target], next[index]];
    setConfigs(next); // optimistic

    try {
      await Promise.all([
        apiClient.patch(`/admin/ai-configs/${next[index].id}`, { order_index: index }),
        apiClient.patch(`/admin/ai-configs/${next[target].id}`, { order_index: target }),
      ]);
      setConfigs((prev) =>
        prev.map((c, i) => (i === index || i === target ? { ...c, order_index: i } : c))
      );
    } catch (error: any) {
      showToast(error.message || "Failed to save the new order.", "error");
      loadConfigs();
    }
  };

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <View style={[styles.header, { borderBottomColor: colors.border }]}>
        <Text style={[styles.headerTitle, { color: colors.textPrimary }]}>AI Models</Text>
        <Text style={[styles.headerSubtitle, { color: colors.textTertiary }]}>
          Platform-default AI providers — these sit in every user's AI model bag alongside
          their own configs.
        </Text>
      </View>

      {isLoading ? (
        <View style={styles.centered}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : (
        <ScrollView contentContainerStyle={styles.content}>
          {configs.length === 0 ? (
            <Text style={{ color: colors.textTertiary, fontSize: 13 }}>
              No platform-default AI models configured yet — VengaiCode falls back to its
              built-in Ollama/Groq settings until you add one here.
            </Text>
          ) : (
            configs.map((config, index) => (
              <View key={config.id} style={[styles.row, { borderColor: colors.border, backgroundColor: colors.surface }]}>
                <Server size={16} color={colors.textTertiary} />
                <View style={{ flex: 1 }}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Text style={[styles.label, { color: colors.textPrimary }]} numberOfLines={1}>
                      {config.label}
                    </Text>
                    {config.is_active ? (
                      <View style={[styles.badge, { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.success }]}>
                        <Check size={9} color={colors.success} />
                        <Text style={{ color: colors.success, fontSize: 9, fontWeight: "700" }}>Active</Text>
                      </View>
                    ) : (
                      <View style={[styles.badge, { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border }]}>
                        <Text style={{ color: colors.textTertiary, fontSize: 9, fontWeight: "700" }}>Paused</Text>
                      </View>
                    )}
                    {config.task_type && (
                      <View style={[styles.badge, { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.primary }]}>
                        <Text style={{ color: colors.primary, fontSize: 9, fontWeight: "700" }}>
                          {config.task_type === "codegen" ? "Codegen only" : "Chat only"}
                        </Text>
                      </View>
                    )}
                  </View>
                  <Text style={{ color: colors.textTertiary, fontSize: 11 }} numberOfLines={1}>
                    {config.provider_type} · {config.model_name}
                  </Text>
                </View>
                <View style={{ flexDirection: "row", gap: 2 }}>
                  <Pressable onPress={() => handleMove(index, -1)} disabled={index === 0} hitSlop={8} style={{ opacity: index === 0 ? 0.3 : 1, padding: 4 }}>
                    <ChevronUp size={15} color={colors.textSecondary} />
                  </Pressable>
                  <Pressable onPress={() => handleMove(index, 1)} disabled={index === configs.length - 1} hitSlop={8} style={{ opacity: index === configs.length - 1 ? 0.3 : 1, padding: 4 }}>
                    <ChevronDown size={15} color={colors.textSecondary} />
                  </Pressable>
                </View>
                <Switch
                  value={config.is_active}
                  onValueChange={() => handleToggleActive(config)}
                  trackColor={{ true: colors.primary, false: colors.border }}
                />
                <Pressable onPress={() => handleDelete(config)} hitSlop={8}>
                  <Trash2 size={15} color={colors.textTertiary} />
                </Pressable>
              </View>
            ))
          )}

          {showForm ? (
            <View style={[styles.formArea, { borderColor: colors.border, backgroundColor: colors.surface }]}>
              <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>Provider</Text>
              <View style={styles.chipRow}>
                {PROVIDERS.map((p) => {
                  const selected = form.provider_type === p.value;
                  return (
                    <Pressable
                      key={p.value}
                      onPress={() => setForm((f) => ({ ...f, provider_type: p.value }))}
                      style={[
                        styles.chip,
                        { borderColor: selected ? colors.primary : colors.border, backgroundColor: selected ? colors.primaryLight : colors.background },
                      ]}
                    >
                      <Text style={{ color: selected ? colors.primary : colors.textSecondary, fontSize: 11, fontWeight: "600" }}>{p.label}</Text>
                    </Pressable>
                  );
                })}
              </View>

              {(form.provider_type === "custom" || form.provider_type === "ollama") && (
                <>
                  <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>
                    Base URL {form.provider_type === "custom" && "*"}
                  </Text>
                  <TextInput
                    value={form.base_url}
                    onChangeText={(v) => setForm((f) => ({ ...f, base_url: v }))}
                    placeholder={form.provider_type === "ollama" ? "Defaults to the backend's Ollama host" : "https://your-endpoint.example.com/v1"}
                    placeholderTextColor={colors.textTertiary}
                    autoCapitalize="none"
                    style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
                  />
                </>
              )}

              {form.provider_type !== "ollama" && (
                <>
                  <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>API key *</Text>
                  <TextInput
                    value={form.api_key}
                    onChangeText={(v) => setForm((f) => ({ ...f, api_key: v }))}
                    placeholder="sk-..."
                    placeholderTextColor={colors.textTertiary}
                    secureTextEntry
                    autoCapitalize="none"
                    style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
                  />
                </>
              )}

              <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>Model name *</Text>
              <TextInput
                value={form.model_name}
                onChangeText={(v) => setForm((f) => ({ ...f, model_name: v }))}
                placeholder="e.g. openai/gpt-oss-120b, qwen2.5-coder"
                placeholderTextColor={colors.textTertiary}
                autoCapitalize="none"
                style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
              />

              <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>Label *</Text>
              <TextInput
                value={form.label}
                onChangeText={(v) => setForm((f) => ({ ...f, label: v }))}
                placeholder="e.g. Company Groq account"
                placeholderTextColor={colors.textTertiary}
                style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
              />

              <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>Use for</Text>
              <View style={styles.chipRow}>
                {TASK_TYPES.map((t) => {
                  const selected = form.task_type === t.value;
                  return (
                    <Pressable
                      key={t.value || "any"}
                      onPress={() => setForm((f) => ({ ...f, task_type: t.value }))}
                      style={[
                        styles.chip,
                        { borderColor: selected ? colors.primary : colors.border, backgroundColor: selected ? colors.primaryLight : colors.background },
                      ]}
                    >
                      <Text style={{ color: selected ? colors.primary : colors.textSecondary, fontSize: 11, fontWeight: "600" }}>{t.label}</Text>
                    </Pressable>
                  );
                })}
              </View>

              <View style={{ flexDirection: "row", gap: 10, marginTop: 4 }}>
                <Pressable onPress={handleSave} disabled={isSaving} style={[styles.saveButton, { backgroundColor: colors.primary, opacity: isSaving ? 0.6 : 1 }]}>
                  <Text style={{ color: "#fff", fontWeight: "700", fontSize: 13 }}>Add platform default</Text>
                </Pressable>
                <Pressable onPress={resetForm} style={[styles.cancelButton, { borderColor: colors.border }]}>
                  <Text style={{ color: colors.textSecondary, fontSize: 13, fontWeight: "600" }}>Cancel</Text>
                </Pressable>
              </View>
            </View>
          ) : (
            <Pressable onPress={() => setShowForm(true)} style={styles.addRow}>
              <Plus size={14} color={colors.primary} />
              <Text style={{ color: colors.primary, fontSize: 13, fontWeight: "600" }}>Add platform-default AI model</Text>
            </Pressable>
          )}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  header: { padding: 20, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { fontSize: 20, fontWeight: "700" },
  headerSubtitle: { fontSize: 12, marginTop: 4, lineHeight: 16 },
  centered: { flex: 1, alignItems: "center", justifyContent: "center" },
  content: { padding: 16, gap: 8, paddingBottom: 32 },
  row: { flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1, borderRadius: 12, padding: 10 },
  label: { fontSize: 13, fontWeight: "600", flexShrink: 1 },
  badge: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 5, paddingVertical: 1, borderRadius: 999 },
  formArea: { borderWidth: 1, borderRadius: 12, padding: 12, gap: 6, marginTop: 4 },
  fieldLabel: { fontSize: 12, fontWeight: "600", marginTop: 6 },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 13 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 8 },
  saveButton: { flex: 1, borderRadius: 10, paddingVertical: 12, alignItems: "center" },
  cancelButton: { borderWidth: 1, borderRadius: 10, paddingVertical: 12, paddingHorizontal: 16, alignItems: "center" },
  addRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 },
});
