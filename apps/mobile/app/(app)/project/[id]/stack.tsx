import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { AlertTriangle, CheckCircle2, ChevronRight, XCircle } from "lucide-react-native";

import apiClient from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import PhaseHeader from "@/components/phase/PhaseHeader";
import PhaseLoading from "@/components/phase/PhaseLoading";
import PhaseFooter from "@/components/phase/PhaseFooter";

interface StackSelection {
  frontend_language: string;
  frontend_framework: string;
  backend_language: string;
  backend_framework: string;
  api_style: string;
}

interface FrontendFrameworkOption {
  key: string;
  label: string;
  languages: string[];
  category: string;
}

interface BackendFrameworkOption {
  key: string;
  label: string;
  languages: string[];
  supported_api_styles: string[];
}

interface StackOptions {
  frontend_frameworks: FrontendFrameworkOption[];
  backend_frameworks: BackendFrameworkOption[];
  api_styles: string[];
  recommended_default: StackSelection;
}

interface StackCombo {
  selection: StackSelection;
  frontend_label: string;
  backend_label: string;
  buildable_now: boolean;
}

interface ValidateResult {
  status: "ok" | "coherent_not_buildable" | "incoherent";
  coherent: boolean;
  buildable_now: boolean;
  coherence_errors: string[];
  message: string;
  suggestion: StackCombo | null;
}

const VALIDATE_DEBOUNCE_MS = 400;
const WARNING_COLOR = "#eab308";

function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function StackScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [options, setOptions] = useState<StackOptions | null>(null);
  const [selection, setSelection] = useState<StackSelection | null>(null);
  const [validation, setValidation] = useState<ValidateResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isValidating, setIsValidating] = useState(false);
  const [isContinuing, setIsContinuing] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    loadOptions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    if (!selection) return;
    setIsValidating(true);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runValidate(selection), VALIDATE_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection]);

  const loadOptions = async () => {
    try {
      const { data } = await apiClient.get("/stack/options", { params: { project_id: projectId } });
      setOptions(data);

      let initial: StackSelection = data.recommended_default;
      try {
        const { data: saved } = await apiClient.get(`/stack/${projectId}`);
        if (saved?.selected_stack) {
          const { buildable_now, validated_at, ...rest } = saved.selected_stack;
          initial = rest as StackSelection;
        }
      } catch {
        // No prior selection — use the recommended default.
      }
      setSelection(initial);
    } catch (error: any) {
      showToast(error.message || "Failed to load stack options.", "error");
      router.replace(`/(app)/project/${projectId}/uiux` as any);
    } finally {
      setIsLoading(false);
    }
  };

  const runValidate = async (sel: StackSelection) => {
    try {
      const { data } = await apiClient.post("/stack/validate", { selection: sel });
      setValidation(data);
    } catch (error: any) {
      showToast(error.message || "Failed to validate stack.", "error");
    } finally {
      setIsValidating(false);
    }
  };

  const handleContinue = async () => {
    if (!selection) return;
    setIsContinuing(true);
    try {
      await apiClient.post("/stack/select", { project_id: projectId, selection });
      showToast("Stack saved! Next: Architecture 🐯");
      router.replace(`/(app)/project/${projectId}/architecture` as any);
    } catch (error: any) {
      showToast(error.message || "Failed to save stack.", "error");
    } finally {
      setIsContinuing(false);
    }
  };

  const useSuggestion = () => {
    if (!validation?.suggestion) return;
    setSelection(validation.suggestion.selection);
  };

  const updateFrontendFramework = (frameworkKey: string) => {
    if (!options || !selection) return;
    const framework = options.frontend_frameworks.find((f) => f.key === frameworkKey);
    if (!framework) return;
    const language = framework.languages.includes(selection.frontend_language)
      ? selection.frontend_language
      : framework.languages[0] || selection.frontend_language;
    setSelection({ ...selection, frontend_framework: frameworkKey, frontend_language: language });
  };

  const updateBackendFramework = (frameworkKey: string) => {
    if (!options || !selection) return;
    const framework = options.backend_frameworks.find((f) => f.key === frameworkKey);
    if (!framework) return;
    const language = framework.languages.includes(selection.backend_language)
      ? selection.backend_language
      : framework.languages[0] || selection.backend_language;
    const apiStyle = framework.supported_api_styles.includes(selection.api_style)
      ? selection.api_style
      : framework.supported_api_styles[0] || selection.api_style;
    setSelection({
      ...selection,
      backend_framework: frameworkKey,
      backend_language: language,
      api_style: apiStyle,
    });
  };

  if (isLoading || !options || !selection) {
    return <PhaseLoading message="Loading tech stack options..." />;
  }

  const selectedFrontend = options.frontend_frameworks.find((f) => f.key === selection.frontend_framework);
  const selectedBackend = options.backend_frameworks.find((f) => f.key === selection.backend_framework);
  const canContinue = validation?.status === "ok";
  const canContinueAnyway = validation?.status === "coherent_not_buildable";

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <PhaseHeader title="Tech Stack" subtitle="Before Architecture — pick your UI, backend, and API style" />

      <ScrollView style={styles.flex} contentContainerStyle={styles.content}>
        <Text style={{ color: colors.textSecondary, fontSize: 12, lineHeight: 17, marginBottom: 4 }}>
          Pick any combination you like — Baby Tiger checks every possibility and tells you
          immediately whether it's possible, and what's closest if it isn't.
        </Text>

        <ChoicePickerRow
          label="UI Framework"
          options={options.frontend_frameworks.map((f) => ({ key: f.key, label: f.label }))}
          value={selection.frontend_framework}
          onChange={updateFrontendFramework}
          colors={colors}
        />
        {selectedFrontend && selectedFrontend.languages.length > 1 && (
          <ChoicePickerRow
            label="UI Language"
            options={selectedFrontend.languages.map((l) => ({ key: l, label: titleCase(l) }))}
            value={selection.frontend_language}
            onChange={(lang) => setSelection({ ...selection, frontend_language: lang })}
            colors={colors}
          />
        )}

        <ChoicePickerRow
          label="Backend Framework"
          options={options.backend_frameworks.map((f) => ({ key: f.key, label: f.label }))}
          value={selection.backend_framework}
          onChange={updateBackendFramework}
          colors={colors}
        />
        {selectedBackend && selectedBackend.languages.length > 1 && (
          <ChoicePickerRow
            label="Backend Language"
            options={selectedBackend.languages.map((l) => ({ key: l, label: titleCase(l) }))}
            value={selection.backend_language}
            onChange={(lang) => setSelection({ ...selection, backend_language: lang })}
            colors={colors}
          />
        )}

        <ChoicePickerRow
          label="API Style"
          options={options.api_styles.map((a) => ({
            key: a,
            label: a.toUpperCase(),
            disabled: !!selectedBackend && !selectedBackend.supported_api_styles.includes(a),
          }))}
          value={selection.api_style}
          onChange={(style) => setSelection({ ...selection, api_style: style })}
          colors={colors}
        />

        {/* Validation banner */}
        {isValidating ? (
          <View style={styles.checkingRow}>
            <ActivityIndicator size="small" color={colors.textSecondary} />
            <Text style={{ color: colors.textSecondary, fontSize: 12 }}>Checking...</Text>
          </View>
        ) : validation?.status === "ok" ? (
          <View style={[styles.banner, { borderColor: colors.success, backgroundColor: colors.success + "22" }]}>
            <CheckCircle2 size={16} color={colors.success} style={{ marginTop: 1 }} />
            <Text style={{ color: colors.textPrimary, fontSize: 12, flex: 1, lineHeight: 17 }}>
              {validation.message}
            </Text>
          </View>
        ) : validation?.status === "coherent_not_buildable" ? (
          <View style={[styles.banner, { flexDirection: "column", gap: 8, borderColor: WARNING_COLOR, backgroundColor: WARNING_COLOR + "22" }]}>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <AlertTriangle size={16} color={WARNING_COLOR} style={{ marginTop: 1 }} />
              <Text style={{ color: colors.textPrimary, fontSize: 12, flex: 1, lineHeight: 17 }}>
                {validation.message}
                {validation.suggestion && (
                  <>
                    {" "}Nearest buildable:{" "}
                    <Text style={{ fontWeight: "700" }}>
                      {validation.suggestion.frontend_label} + {validation.suggestion.backend_label}
                    </Text>.
                  </>
                )}
              </Text>
            </View>
            <Pressable onPress={useSuggestion} style={[styles.suggestionButton, { backgroundColor: colors.primary }]}>
              <Text style={styles.suggestionButtonText}>Use Suggested Stack</Text>
            </Pressable>
          </View>
        ) : validation?.status === "incoherent" ? (
          <View style={[styles.banner, { flexDirection: "column", gap: 8, borderColor: colors.error, backgroundColor: colors.error + "22" }]}>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <XCircle size={16} color={colors.error} style={{ marginTop: 1 }} />
              <View style={{ flex: 1, gap: 2 }}>
                {validation.coherence_errors.map((err, i) => (
                  <Text key={i} style={{ color: colors.textPrimary, fontSize: 12, lineHeight: 17 }}>{err}</Text>
                ))}
              </View>
            </View>
            {validation.suggestion && (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <Text style={{ color: colors.textSecondary, fontSize: 12, flex: 1 }}>
                  Nearest possible:{" "}
                  <Text style={{ fontWeight: "700", color: colors.textPrimary }}>
                    {validation.suggestion.frontend_label} + {validation.suggestion.backend_label}
                  </Text>
                </Text>
                <Pressable onPress={useSuggestion} style={[styles.suggestionButton, { backgroundColor: colors.primary }]}>
                  <Text style={styles.suggestionButtonText}>Use This</Text>
                </Pressable>
              </View>
            )}
          </View>
        ) : null}
      </ScrollView>

      <PhaseFooter
        note={canContinueAnyway ? "This stack is valid but not buildable yet — you can still save it." : "Baby Tiger will use exactly what you pick here for Architecture and Code Generation."}
        secondaryActions={canContinueAnyway ? [{ label: "Continue Anyway", icon: ChevronRight, onPress: handleContinue, loading: isContinuing }] : undefined}
        primaryLabel="Continue"
        primaryIcon={ChevronRight}
        onPrimaryPress={handleContinue}
        primaryLoading={isContinuing}
        primaryDisabled={!canContinue}
      />
    </View>
  );
}

function ChoicePickerRow({
  label,
  options,
  value,
  onChange,
  colors,
}: {
  label: string;
  options: { key: string; label: string; disabled?: boolean }[];
  value: string;
  onChange: (key: string) => void;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={styles.pickerCard}>
      <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "700", marginBottom: 8 }}>{label}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {options.map((opt) => (
          <Pressable
            key={opt.key}
            onPress={() => !opt.disabled && onChange(opt.key)}
            disabled={opt.disabled}
            style={[
              styles.pill,
              { borderColor: value === opt.key ? colors.primary : colors.border },
              value === opt.key && { backgroundColor: colors.primaryLight },
              opt.disabled && { opacity: 0.3 },
            ]}
          >
            <Text style={{ color: value === opt.key ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>
              {opt.label}
            </Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  flex: { flex: 1 },
  content: { padding: 16, gap: 14 },
  pickerCard: {},
  pill: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 7 },
  checkingRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  banner: { flexDirection: "row", gap: 8, borderWidth: 1, borderRadius: 12, padding: 12 },
  suggestionButton: { alignSelf: "flex-start", borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
  suggestionButtonText: { color: "#fff", fontWeight: "700", fontSize: 12 },
});
