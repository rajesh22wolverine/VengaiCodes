import { useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { BookOpen, Layout, Navigation, Palette, Puzzle, ThumbsUp, Type } from "lucide-react-native";

import apiClient from "@/lib/api";
import { downloadAndShareFile } from "@/lib/download";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import PhaseHeader from "@/components/phase/PhaseHeader";
import PhaseLoading from "@/components/phase/PhaseLoading";
import PhaseFooter from "@/components/phase/PhaseFooter";
import Section from "@/components/ui/Section";

interface ScreenDefinition {
  name: string;
  purpose: string;
  key_elements: string[];
}

interface ColorPalette {
  primary: string;
  secondary: string;
  accent: string;
  background: string;
  text: string;
}

interface UIUXDesign {
  design_style: string;
  color_palette: ColorPalette;
  typography: string;
  screens: ScreenDefinition[];
  components: string[];
  navigation_pattern: string;
}

export default function UIUXScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [design, setDesign] = useState<UIUXDesign | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/uiux/${projectId}`);
      setDesign(data.design);
      setIsLoading(false);
    } catch {
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/uiux/generate", { project_id: projectId });
      setDesign(data.design);
      showToast("Your design system is ready! 🎨🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to generate design.", "error");
      router.replace(`/(app)/project/${projectId}/requirements` as any);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownloadDocs = async () => {
    setIsDownloadingDocs(true);
    try {
      await downloadAndShareFile(`/export/${projectId}/documents`, "documentation.zip");
      showToast("Documentation bundle downloaded 🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to download documentation.", "error");
    } finally {
      setIsDownloadingDocs(false);
    }
  };

  const handleApprove = async () => {
    setIsApproving(true);
    try {
      await apiClient.post("/uiux/approve", { project_id: projectId, approved: true });
      showToast("Design approved! Next: Architecture 🐯");
      router.replace(`/(app)/project/${projectId}/architecture` as any);
    } catch (error: any) {
      showToast(error.message || "Failed to approve.", "error");
    } finally {
      setIsApproving(false);
    }
  };

  if (isLoading || isGenerating) {
    return <PhaseLoading message={isGenerating ? "Baby Tiger is designing your app... 🎨🐯" : "Loading..."} />;
  }

  if (!design) return null;

  const colorEntries = Object.entries(design.color_palette) as [keyof ColorPalette, string][];

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <PhaseHeader title="UI/UX Design" subtitle="Phase 2 of 7 — Review and approve to continue" />

      <ScrollView contentContainerStyle={styles.content}>
        <Section icon={Palette} title="Design Style">
          <Text style={[styles.body, { color: colors.textSecondary }]}>{design.design_style}</Text>
        </Section>

        <Section icon={Palette} title="Color Palette">
          <View style={styles.colorGrid}>
            {colorEntries.map(([key, hex]) => (
              <View key={key} style={styles.colorItem}>
                <View style={[styles.colorSwatch, { backgroundColor: hex, borderColor: colors.border }]} />
                <Text style={{ color: colors.textPrimary, fontSize: 11, fontWeight: "600", textTransform: "capitalize" }}>
                  {key}
                </Text>
                <Text style={{ color: colors.textTertiary, fontSize: 10 }}>{hex}</Text>
              </View>
            ))}
          </View>
        </Section>

        <Section icon={Type} title="Typography">
          <Text style={[styles.body, { color: colors.textSecondary }]}>{design.typography}</Text>
        </Section>

        <Section icon={Layout} title={`Screens (${design.screens.length})`}>
          {design.screens.map((screen, i) => (
            <View key={i} style={[styles.screenCard, { backgroundColor: colors.background, borderColor: colors.border }]}>
              <View style={styles.screenHeaderRow}>
                <View style={[styles.dot, { backgroundColor: design.color_palette.primary }]} />
                <Text style={[styles.screenName, { color: colors.textPrimary }]}>{screen.name}</Text>
              </View>
              <Text style={[styles.body, { color: colors.textSecondary, marginBottom: 8 }]}>{screen.purpose}</Text>
              <View style={styles.pillRow}>
                {screen.key_elements.map((el, j) => (
                  <View key={j} style={[styles.elementPill, { backgroundColor: colors.surface, borderColor: colors.border }]}>
                    <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{el}</Text>
                  </View>
                ))}
              </View>
            </View>
          ))}
        </Section>

        <Section icon={Puzzle} title="Reusable Components">
          <View style={styles.pillRow}>
            {design.components.map((component, i) => (
              <View key={i} style={[styles.pill, { backgroundColor: colors.primaryLight }]}>
                <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "600", textTransform: "capitalize" }}>
                  {component}
                </Text>
              </View>
            ))}
          </View>
        </Section>

        <Section icon={Navigation} title="Navigation Pattern">
          <Text style={[styles.body, { color: colors.textSecondary }]}>{design.navigation_pattern}</Text>
        </Section>
      </ScrollView>

      <PhaseFooter
        note="Review the design above. Once approved, Baby Tiger moves to Architecture 🏗️"
        secondaryActions={[{ label: "Export Docs", icon: BookOpen, onPress: handleDownloadDocs, loading: isDownloadingDocs }]}
        primaryLabel="Approve & Continue"
        primaryIcon={ThumbsUp}
        onPrimaryPress={handleApprove}
        primaryLoading={isApproving}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { padding: 16 },
  body: { fontSize: 13, lineHeight: 19 },
  colorGrid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  colorItem: { alignItems: "center", width: 64, gap: 4 },
  colorSwatch: { width: 48, height: 48, borderRadius: 12, borderWidth: 1 },
  screenCard: { borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 10 },
  screenHeaderRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  screenName: { fontSize: 13, fontWeight: "700" },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 10 },
  elementPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, borderWidth: 1 },
});
