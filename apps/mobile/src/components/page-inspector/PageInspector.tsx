import { useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { AlertTriangle, Check, ScanSearch, Wand2, X } from "lucide-react-native";

import apiClient from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";

/**
 * UI for the deterministic page engine (backend: /api/v1/page/*).
 *
 * Nothing here calls an AI model. Analysis is a real parse of the page,
 * and a change request is matched against an explicit rule table — so
 * anything it doesn't understand comes back as a refusal listing what it
 * *does* understand, instead of a model guessing at an edit. The refusal
 * state is shown as prominently as success on purpose.
 */

interface PageIssue {
  type: string;
  index: number | null;
  message: string;
}

interface PageSummary {
  element_count: number;
  headings: unknown[];
  links: unknown[];
  images: unknown[];
  forms: unknown[];
  buttons: unknown[];
  colors_used: string[];
  word_count: number;
  stylesheet: { rule_count: number };
}

interface CommandResponse {
  understood: { explanation: string }[];
  not_understood: { error: string; suggestions: string[] }[];
  applied: boolean;
  html?: string;
  css?: string;
}

export default function PageInspector({
  html,
  css,
  onApply,
}: {
  html: string;
  css: string;
  onApply: (html: string, css: string) => void;
}) {
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [summary, setSummary] = useState<PageSummary | null>(null);
  const [issues, setIssues] = useState<PageIssue[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [command, setCommand] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<CommandResponse | null>(null);

  const analyze = async () => {
    if (!html.trim()) {
      showToast("This page has no HTML to analyze yet.", "error");
      return;
    }
    setIsAnalyzing(true);
    try {
      const { data } = await apiClient.post("/page/analyze", { html, css });
      setSummary(data.summary);
      setIssues(data.issues || []);
    } catch (error: any) {
      showToast(error.message || "Couldn't analyze this page.", "error");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const runCommand = async (apply: boolean) => {
    if (!command.trim()) return;
    setIsRunning(true);
    try {
      const { data } = await apiClient.post("/page/command", { html, css, command, apply });
      setResult(data);
      if (apply && data.applied) {
        onApply(data.html, data.css);
        setCommand("");
        showToast("Change applied 🐯");
        // The page changed underneath it, so the old inventory is stale.
        setSummary(null);
        setIssues([]);
      }
    } catch (error: any) {
      showToast(error.message || "Couldn't run that change.", "error");
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <View style={styles.titleRow}>
            <ScanSearch size={14} color={colors.primary} />
            <Text style={{ color: colors.textPrimary, fontSize: 13, fontWeight: "700" }}>Page Inspector</Text>
          </View>
          <Text style={{ color: colors.textTertiary, fontSize: 11, marginTop: 2 }}>
            Reads and edits this page directly — no AI, no token cost.
          </Text>
        </View>
        <Pressable
          onPress={analyze}
          disabled={isAnalyzing}
          style={[styles.secondaryButton, { borderColor: colors.border, opacity: isAnalyzing ? 0.6 : 1 }]}
        >
          {isAnalyzing ? (
            <ActivityIndicator size="small" color={colors.primary} />
          ) : (
            <Text style={{ color: colors.textPrimary, fontSize: 11, fontWeight: "600" }}>Analyze</Text>
          )}
        </Pressable>
      </View>

      {summary && (
        <View style={styles.statRow}>
          <Stat label="elements" value={summary.element_count} />
          <Stat label="headings" value={summary.headings.length} />
          <Stat label="links" value={summary.links.length} />
          <Stat label="images" value={summary.images.length} />
          <Stat label="forms" value={summary.forms.length} />
          <Stat label="css rules" value={summary.stylesheet.rule_count} />
          <Stat label="words" value={summary.word_count} />
        </View>
      )}

      {issues.length > 0 && (
        <View style={[styles.issueBox, { borderColor: colors.border }]}>
          <View style={styles.titleRow}>
            <AlertTriangle size={13} color="#eab308" />
            <Text style={{ color: "#eab308", fontSize: 11, fontWeight: "700" }}>
              {issues.length} thing{issues.length === 1 ? "" : "s"} worth fixing
            </Text>
          </View>
          {issues.slice(0, 5).map((issue, i) => (
            <Text key={i} style={{ color: colors.textSecondary, fontSize: 11, marginTop: 3 }}>
              • {issue.message}
              {issue.index !== null ? ` (element ${issue.index})` : ""}
            </Text>
          ))}
        </View>
      )}

      <Text style={{ color: colors.textSecondary, fontSize: 11, fontWeight: "600", marginTop: 10, marginBottom: 6 }}>
        Describe a change
      </Text>
      <View style={styles.commandRow}>
        <TextInput
          value={command}
          onChangeText={setCommand}
          placeholder="e.g. make the header background #2563eb"
          placeholderTextColor={colors.textTertiary}
          autoCapitalize="none"
          style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
        />
        <Pressable
          onPress={() => runCommand(false)}
          disabled={isRunning || !command.trim()}
          style={[styles.primaryButton, { backgroundColor: colors.primary, opacity: isRunning || !command.trim() ? 0.6 : 1 }]}
        >
          {isRunning ? <ActivityIndicator size="small" color="#fff" /> : <Wand2 size={13} color="#fff" />}
          <Text style={{ color: "#fff", fontSize: 11, fontWeight: "700" }}>Preview</Text>
        </Pressable>
      </View>

      {result && (
        <View style={{ marginTop: 8, gap: 6 }}>
          {result.understood.map((item, i) => (
            <View key={i} style={styles.titleRow}>
              <Check size={13} color="#22c55e" />
              <Text style={{ color: colors.textSecondary, fontSize: 11, flex: 1 }}>{item.explanation}</Text>
            </View>
          ))}

          {result.not_understood.map((item, i) => (
            <View key={i} style={[styles.issueBox, { borderColor: colors.border }]}>
              <View style={styles.titleRow}>
                <X size={13} color="#ef4444" />
                <Text style={{ color: colors.textSecondary, fontSize: 11, flex: 1 }}>{item.error}</Text>
              </View>
              {item.suggestions?.length > 0 && (
                <>
                  <Text style={{ color: colors.textTertiary, fontSize: 10, marginTop: 6, marginBottom: 4 }}>
                    Try one of these instead:
                  </Text>
                  <View style={styles.suggestionRow}>
                    {item.suggestions.slice(0, 5).map((suggestion) => (
                      <Pressable
                        key={suggestion}
                        onPress={() => setCommand(suggestion)}
                        style={[styles.suggestionPill, { borderColor: colors.border, backgroundColor: colors.surface }]}
                      >
                        <Text style={{ color: colors.textTertiary, fontSize: 10 }}>{suggestion}</Text>
                      </Pressable>
                    ))}
                  </View>
                </>
              )}
            </View>
          ))}

          {result.understood.length > 0 && !result.applied && (
            <Pressable
              onPress={() => runCommand(true)}
              disabled={isRunning}
              style={[styles.applyButton, { backgroundColor: colors.primary, opacity: isRunning ? 0.6 : 1 }]}
            >
              {isRunning ? <ActivityIndicator size="small" color="#fff" /> : <Check size={13} color="#fff" />}
              <Text style={{ color: "#fff", fontSize: 12, fontWeight: "700" }}>
                Apply {result.understood.length === 1 ? "this change" : `these ${result.understood.length} changes`}
              </Text>
            </Pressable>
          )}
        </View>
      )}
    </View>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.statPill, { borderColor: colors.border, backgroundColor: colors.background }]}>
      <Text style={{ color: colors.textPrimary, fontSize: 10, fontWeight: "700" }}>{value}</Text>
      <Text style={{ color: colors.textSecondary, fontSize: 10 }}> {label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 12, padding: 12, marginTop: 10, marginBottom: 10 },
  headerRow: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  titleRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  secondaryButton: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6 },
  statRow: { flexDirection: "row", flexWrap: "wrap", gap: 5, marginTop: 10 },
  statPill: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2 },
  issueBox: { borderWidth: 1, borderRadius: 8, padding: 8, marginTop: 8 },
  commandRow: { flexDirection: "row", gap: 6 },
  input: { flex: 1, borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 11 },
  primaryButton: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, borderRadius: 8, paddingHorizontal: 12 },
  applyButton: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: 8, paddingVertical: 10, marginTop: 4 },
  suggestionRow: { flexDirection: "row", flexWrap: "wrap", gap: 4 },
  suggestionPill: { borderWidth: 1, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 3 },
});
