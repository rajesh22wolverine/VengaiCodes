import { useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { BookOpen, CheckCircle2, Code2, DollarSign, Smartphone, Sparkles, Target, ThumbsUp, Users } from "lucide-react-native";

import apiClient from "@/lib/api";
import { downloadAndShareFile } from "@/lib/download";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import PhaseHeader from "@/components/phase/PhaseHeader";
import PhaseLoading from "@/components/phase/PhaseLoading";
import PhaseFooter from "@/components/phase/PhaseFooter";
import Section from "@/components/ui/Section";

interface RequirementsDocument {
  overview: string;
  problem_statement: string;
  target_users: string;
  key_features: string[];
  platforms: string[];
  monetization: string;
  reference_apps: string[];
  user_stories: string[];
  tech_recommendations: string;
}

export default function RequirementsScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [requirements, setRequirements] = useState<RequirementsDocument | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/requirements/${projectId}`);
      setRequirements(data.requirements);
      setIsLoading(false);
    } catch {
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/requirements/generate", { project_id: projectId });
      setRequirements(data.requirements);
      showToast("Your requirements document is ready! 🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to generate requirements.", "error");
      router.replace(`/(app)/project/${projectId}/wizard` as any);
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
      await apiClient.post("/requirements/approve", { project_id: projectId, approved: true });
      showToast("Requirements approved! Next: UI/UX Design 🐯");
      router.replace(`/(app)/project/${projectId}/uiux` as any);
    } catch (error: any) {
      showToast(error.message || "Failed to approve.", "error");
    } finally {
      setIsApproving(false);
    }
  };

  if (isLoading || isGenerating) {
    return (
      <PhaseLoading message={isGenerating ? "Baby Tiger is organizing your requirements... 🐯" : "Loading..."} />
    );
  }

  if (!requirements) return null;

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <PhaseHeader title="Requirements Document" subtitle="Phase 1 of 7 — Review and approve to continue" />

      <ScrollView contentContainerStyle={styles.content}>
        <Section icon={Sparkles} title="Overview">
          <Text style={[styles.body, { color: colors.textSecondary }]}>{requirements.overview}</Text>
        </Section>

        <Section icon={Target} title="Problem Statement">
          <Text style={[styles.body, { color: colors.textSecondary }]}>{requirements.problem_statement}</Text>
        </Section>

        <Section icon={Users} title="Target Users">
          <Text style={[styles.body, { color: colors.textSecondary }]}>{requirements.target_users}</Text>
        </Section>

        <Section icon={CheckCircle2} title="Key Features">
          {requirements.key_features.map((feature, i) => (
            <View key={i} style={styles.listRow}>
              <CheckCircle2 size={15} color={colors.success} style={{ marginTop: 2 }} />
              <Text style={[styles.body, { color: colors.textSecondary, flex: 1 }]}>{feature}</Text>
            </View>
          ))}
        </Section>

        <Section icon={Smartphone} title="Platforms">
          <View style={styles.pillRow}>
            {requirements.platforms.map((platform, i) => (
              <View key={i} style={[styles.pill, { backgroundColor: colors.primaryLight }]}>
                <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "600" }}>{platform}</Text>
              </View>
            ))}
          </View>
        </Section>

        <Section icon={DollarSign} title="Monetization">
          <Text style={[styles.body, { color: colors.textSecondary }]}>{requirements.monetization}</Text>
        </Section>

        <Section icon={BookOpen} title="User Stories">
          {requirements.user_stories.map((story, i) => (
            <View key={i} style={[styles.storyCard, { backgroundColor: colors.background, borderLeftColor: colors.primary }]}>
              <Text style={[styles.body, { color: colors.textSecondary }]}>{story}</Text>
            </View>
          ))}
        </Section>

        <Section icon={Code2} title="Tech Recommendations">
          <Text style={[styles.body, { color: colors.textSecondary }]}>{requirements.tech_recommendations}</Text>
        </Section>

        {requirements.reference_apps.length > 0 && (
          <Section icon={Sparkles} title="Similar Apps">
            <View style={styles.pillRow}>
              {requirements.reference_apps.map((app, i) => (
                <View key={i} style={[styles.pill, { backgroundColor: colors.background }]}>
                  <Text style={{ color: colors.textSecondary, fontSize: 12, fontWeight: "600" }}>{app}</Text>
                </View>
              ))}
            </View>
          </Section>
        )}
      </ScrollView>

      <PhaseFooter
        note="Review everything above. Once approved, Baby Tiger moves to UI/UX Design 🎨"
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
  listRow: { flexDirection: "row", gap: 8, marginBottom: 8 },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 10 },
  storyCard: { padding: 12, borderRadius: 10, borderLeftWidth: 3, marginBottom: 10 },
});
