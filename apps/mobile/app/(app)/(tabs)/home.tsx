import { useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { router } from "expo-router";
import { CheckCircle2, Clock, Plus, Sparkles } from "lucide-react-native";

import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { createProject, deleteProject, fetchProjects, Project } from "@/store/slices/projectSlice";
import { setActiveTab } from "@/store/slices/uiSlice";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import ProjectCard from "@/components/project/ProjectCard";
import BabyTiger from "@/components/BabyTiger";

type TabId = "create" | "pending" | "completed";

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: "create", label: "Create", icon: Plus },
  { id: "pending", label: "Pending", icon: Clock },
  { id: "completed", label: "Completed", icon: CheckCircle2 },
];

const EXAMPLE_IDEAS = [
  "A food delivery app like Swiggy but only for home cooks",
  "A habit tracker that celebrates streaks with animations",
  "A marketplace for renting out unused parking spots",
  "An app like Instagram but for sharing recipes with cooking steps",
];

export default function HomeScreen() {
  const dispatch = useAppDispatch();
  const { colors } = useTheme();
  const { activeTab } = useAppSelector((state) => state.ui);
  const { projects, isLoading: projectsLoading } = useAppSelector((state) => state.project);

  useEffect(() => {
    dispatch(fetchProjects());
  }, [dispatch]);

  const pendingProjects = projects.filter((p) => p.status === "draft" || p.status === "in_progress");
  const completedProjects = projects.filter((p) => p.status === "completed");

  const badgeFor = (tab: TabId) => {
    if (tab === "pending") return pendingProjects.length || undefined;
    if (tab === "completed") return completedProjects.length || undefined;
    return undefined;
  };

  const handleDelete = (id: string) => dispatch(deleteProject(id));

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <View style={[styles.header, { borderBottomColor: colors.border }]}>
        <Text style={[styles.headerTitle, { color: colors.textPrimary }]}>Dashboard</Text>
      </View>

      <View style={[styles.tabBar, { borderBottomColor: colors.border }]}>
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          const badge = badgeFor(tab.id);
          return (
            <Pressable key={tab.id} onPress={() => dispatch(setActiveTab(tab.id))} style={styles.tabButton}>
              <Icon size={16} color={isActive ? colors.primary : colors.textTertiary} />
              <Text style={{ color: isActive ? colors.primary : colors.textSecondary, fontSize: 13, fontWeight: "600" }}>
                {tab.label}
              </Text>
              {badge !== undefined && (
                <View style={[styles.badge, { backgroundColor: isActive ? colors.primary : colors.border }]}>
                  <Text style={{ color: isActive ? "#fff" : colors.textTertiary, fontSize: 10, fontWeight: "700" }}>
                    {badge}
                  </Text>
                </View>
              )}
              {isActive && <View style={[styles.activeIndicator, { backgroundColor: colors.primary }]} />}
            </Pressable>
          );
        })}
      </View>

      {activeTab === "create" && <CreateTab />}
      {activeTab === "pending" && (
        <ProjectList projects={pendingProjects} isLoading={projectsLoading} onDelete={handleDelete} emptyTitle="No projects in progress" emptySubtitle="Start building something new from the Create tab! 🐯" />
      )}
      {activeTab === "completed" && (
        <ProjectList projects={completedProjects} isLoading={projectsLoading} onDelete={handleDelete} emptyTitle="No completed projects yet" emptySubtitle="Your finished apps will appear here, ready to export 🐯" />
      )}
    </View>
  );
}

function CreateTab() {
  const dispatch = useAppDispatch();
  const { colors } = useTheme();
  const { showToast } = useToast();
  const { isLoading } = useAppSelector((state) => state.project);
  const { user } = useAppSelector((state) => state.auth);
  const [idea, setIdea] = useState("");

  const canCreate = user ? user.projects_remaining > 0 : true;

  const handleSubmit = async () => {
    if (!idea.trim()) {
      showToast("Tell Baby Tiger what you want to build first! 🐯", "error");
      return;
    }
    if (!canCreate) {
      showToast("You've used all your free projects. Upgrade to create more! 🐯", "error");
      return;
    }

    const name = idea.trim().slice(0, 50);
    const result = await dispatch(createProject({ name, rawIdea: idea.trim() }));

    if (createProject.fulfilled.match(result)) {
      showToast("Let's understand your idea! 🐯");
      router.push(`/(app)/project/${result.payload.id}/wizard` as any);
    }
  };

  const remainingLabel = user
    ? user.projects_remaining === -1 || user.projects_limit === -1
      ? "Unlimited projects available"
      : `${user.projects_remaining} of ${user.projects_limit} project${user.projects_limit === 1 ? "" : "s"} remaining`
    : "";

  return (
    <ScrollView contentContainerStyle={styles.createScroll} keyboardShouldPersistTaps="handled">
      <View style={styles.hero}>
        <BabyTiger size={56} expression="excited" style={styles.heroEmoji} />
        <Text style={[styles.heroTitle, { color: colors.textPrimary }]}>What do you want to build today?</Text>
        <Text style={[styles.heroSubtitle, { color: colors.textSecondary }]}>
          Describe your idea in plain English. Baby Tiger will ask a few smart questions, then build your complete
          app — Web, Mobile, Desktop — in under 30 minutes.
        </Text>
      </View>

      <TextInput
        value={idea}
        onChangeText={setIdea}
        placeholder="e.g. I want a food delivery app like Swiggy but only for home cooks in my neighbourhood..."
        placeholderTextColor={colors.textTertiary}
        multiline
        numberOfLines={5}
        style={[styles.ideaInput, { color: colors.textPrimary, backgroundColor: colors.surface, borderColor: colors.border }]}
      />

      <View style={styles.createFooterRow}>
        <Text style={{ color: colors.textTertiary, fontSize: 11, flex: 1 }}>{remainingLabel}</Text>
        <Pressable
          onPress={handleSubmit}
          disabled={isLoading || !idea.trim()}
          style={[styles.buildButton, { backgroundColor: colors.primary }, (isLoading || !idea.trim()) && { opacity: 0.6 }]}
        >
          {isLoading ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <>
              <Sparkles size={14} color="#fff" />
              <Text style={styles.buildButtonText}>Build with Baby Tiger</Text>
            </>
          )}
        </Pressable>
      </View>

      <Text style={[styles.inspirationLabel, { color: colors.textTertiary }]}>NEED INSPIRATION?</Text>
      {EXAMPLE_IDEAS.map((example) => (
        <Pressable
          key={example}
          onPress={() => setIdea(example)}
          style={[styles.exampleCard, { borderColor: colors.border, backgroundColor: colors.surface }]}
        >
          <Text style={{ color: colors.textSecondary, fontSize: 13 }}>{example}</Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

function ProjectList({
  projects,
  isLoading,
  onDelete,
  emptyTitle,
  emptySubtitle,
}: {
  projects: Project[];
  isLoading: boolean;
  onDelete: (id: string) => void;
  emptyTitle: string;
  emptySubtitle: string;
}) {
  const { colors } = useTheme();

  if (isLoading && projects.length === 0) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (projects.length === 0) {
    return (
      <View style={styles.centered}>
        <BabyTiger size={56} expression="idle" style={styles.heroEmoji} />
        <Text style={[styles.emptyTitle, { color: colors.textPrimary }]}>{emptyTitle}</Text>
        <Text style={[styles.emptySubtitle, { color: colors.textTertiary }]}>{emptySubtitle}</Text>
      </View>
    );
  }

  return (
    <FlatList
      data={projects}
      keyExtractor={(item) => item.id}
      contentContainerStyle={styles.listContent}
      renderItem={({ item }) => <ProjectCard project={item} onDelete={onDelete} />}
    />
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  header: { padding: 20, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { fontSize: 20, fontWeight: "700" },
  tabBar: { flexDirection: "row", paddingHorizontal: 12, borderBottomWidth: StyleSheet.hairlineWidth },
  tabButton: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 14 },
  badge: { borderRadius: 999, minWidth: 18, height: 18, alignItems: "center", justifyContent: "center", paddingHorizontal: 4 },
  activeIndicator: { position: "absolute", bottom: 0, left: 8, right: 8, height: 2, borderRadius: 2 },
  createScroll: { padding: 20 },
  hero: { alignItems: "center", marginBottom: 20 },
  heroEmoji: { fontSize: 40, textAlign: "center", marginBottom: 8 },
  heroTitle: { fontSize: 20, fontWeight: "700", textAlign: "center", marginBottom: 8 },
  heroSubtitle: { fontSize: 13, textAlign: "center", lineHeight: 19 },
  ideaInput: { borderWidth: 1, borderRadius: 16, padding: 14, fontSize: 14, textAlignVertical: "top", minHeight: 110 },
  createFooterRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: 12, marginBottom: 24 },
  buildButton: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 16, paddingVertical: 10, borderRadius: 12 },
  buildButtonText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  inspirationLabel: { fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginBottom: 10 },
  exampleCard: { borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 8 },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32 },
  emptyTitle: { fontSize: 16, fontWeight: "700", marginBottom: 4 },
  emptySubtitle: { fontSize: 13, textAlign: "center" },
  listContent: { padding: 16 },
});
