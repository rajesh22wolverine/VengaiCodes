import { useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { router } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { CheckCircle2, Clock, Globe, FileText, ImagePlus, Plus, RefreshCw, RotateCcw, ScanLine, Sparkles, X, GitBranch, Wrench } from "lucide-react-native";

import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { createProject, deleteProject, fetchProjects, Project } from "@/store/slices/projectSlice";
import { setActiveTab } from "@/store/slices/uiSlice";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import apiClient from "@/lib/api";
import ProjectCard from "@/components/project/ProjectCard";
import BabyTiger from "@/components/BabyTiger";

type TabId = "create" | "reverse" | "pending" | "completed";

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: "create", label: "Create", icon: Plus },
  { id: "reverse", label: "Reverse App", icon: RefreshCw },
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
      <View style={[styles.header, styles.headerRow, { borderBottomColor: colors.border }]}>
        <Text style={[styles.headerTitle, { color: colors.textPrimary }]}>Dashboard</Text>
        {/* Receives all three Share-via-QR codes: link, blueprint, sequence. */}
        <Pressable
          onPress={() => router.push("/(app)/scan" as any)}
          accessibilityLabel="Scan a VengaiCode QR code"
          style={[styles.scanButton, { borderColor: colors.border }]}
        >
          <ScanLine size={15} color={colors.primary} />
          <Text style={{ color: colors.textPrimary, fontSize: 13, fontWeight: "600" }}>Scan QR</Text>
        </Pressable>
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
      {activeTab === "reverse" && <ReverseAppTab />}
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

  const aiTokensLabel = user
    ? user.ai_tokens_limit === -1
      ? "Unlimited AI tokens available"
      : `${user.ai_tokens_remaining.toLocaleString()} of ${user.ai_tokens_limit.toLocaleString()} AI tokens remaining`
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
        <View style={{ flex: 1 }}>
          <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{remainingLabel}</Text>
          <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{aiTokensLabel}</Text>
        </View>
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

type SourceType = "description" | "url" | "repo" | "screenshots";

const SOURCE_TABS: { id: SourceType; label: string; icon: React.ElementType }[] = [
  { id: "description", label: "Describe", icon: FileText },
  { id: "url", label: "URL", icon: Globe },
  { id: "repo", label: "GitHub", icon: GitBranch },
  { id: "screenshots", label: "Screenshots", icon: ImagePlus },
];

interface ReverseEngineering {
  mode: string;
  tech_stack?: { name: string; category: string; evidence: string }[];
  pages_crawled?: number;
  repo?: string;
  files_scanned?: number;
  data_model?: { name: string }[];
  api_endpoints?: { method: string; path: string }[];
  code_snippets?: { source: string; language: string }[];
}

const MAX_SCREENSHOTS = 5;

function guessPickedImageMimeType(asset: ImagePicker.ImagePickerAsset): string {
  if (asset.mimeType) return asset.mimeType;
  const ext = asset.uri.split(".").pop()?.toLowerCase();
  if (ext === "png") return "image/png";
  if (ext === "webp") return "image/webp";
  return "image/jpeg";
}

function ReverseAppTab() {
  const dispatch = useAppDispatch();
  const { colors } = useTheme();
  const { showToast } = useToast();
  const { isLoading: isCreating } = useAppSelector((state) => state.project);
  const { user } = useAppSelector((state) => state.auth);

  const [sourceType, setSourceType] = useState<SourceType>("description");
  const [description, setDescription] = useState("");
  const [url, setUrl] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [assets, setAssets] = useState<ImagePicker.ImagePickerAsset[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<{ raw_idea: string; suggested_name: string; reverse_engineering: ReverseEngineering } | null>(null);

  const canCreate = user ? user.projects_remaining > 0 : true;

  const addScreenshot = async () => {
    if (assets.length >= MAX_SCREENSHOTS) {
      showToast(`You can add up to ${MAX_SCREENSHOTS} screenshots.`, "error");
      return;
    }
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      showToast("Photo library access is needed to add a screenshot.", "error");
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.9 });
    if (result.canceled || !result.assets[0]) return;
    setAssets((prev) => [...prev, result.assets[0]]);
  };

  const removeScreenshot = (index: number) => {
    setAssets((prev) => prev.filter((_, i) => i !== index));
  };

  const handleAnalyze = async () => {
    if (sourceType === "description" && !description.trim()) {
      showToast("Describe the app you want to clone first! 🐯", "error");
      return;
    }
    if (sourceType === "url" && !url.trim()) {
      showToast("Paste a website URL first! 🐯", "error");
      return;
    }
    if (sourceType === "repo" && !repoUrl.trim()) {
      showToast("Paste a GitHub repo URL first! 🐯", "error");
      return;
    }
    if (sourceType === "screenshots" && assets.length === 0) {
      showToast("Add at least one screenshot first! 🐯", "error");
      return;
    }

    setIsAnalyzing(true);
    try {
      const formData = new FormData();
      formData.append("source_type", sourceType);
      if (sourceType === "description") formData.append("description", description.trim());
      if (sourceType === "url") formData.append("url", url.trim());
      if (sourceType === "repo") formData.append("repo_url", repoUrl.trim());
      if (sourceType === "screenshots") {
        assets.forEach((asset, i) => {
          formData.append(
            "files",
            {
              uri: asset.uri,
              name: asset.fileName || `screenshot-${i}-${Date.now()}.jpg`,
              type: guessPickedImageMimeType(asset),
            } as any
          );
        });
      }

      const { data } = await apiClient.post("/reverse/analyze", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120000,
      });

      setAnalysis({ raw_idea: data.raw_idea, suggested_name: data.suggested_name, reverse_engineering: data.reverse_engineering });
      showToast("Got it! Review the idea below 🐯");
    } catch (error: any) {
      showToast(error.message || "Couldn't analyze that. Please try again!", "error");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleBuild = async () => {
    if (!analysis) return;
    if (!canCreate) {
      showToast("You've used all your free projects. Upgrade to create more! 🐯", "error");
      return;
    }

    const result = await dispatch(
      createProject({
        name: analysis.suggested_name,
        rawIdea: analysis.raw_idea,
        reverseEngineeringData: analysis.reverse_engineering,
      })
    );

    if (createProject.fulfilled.match(result)) {
      showToast("Let's understand your idea! 🐯");
      router.push(`/(app)/project/${result.payload.id}/wizard` as any);
    }
  };

  const reset = () => {
    setAnalysis(null);
    setDescription("");
    setUrl("");
    setRepoUrl("");
    setAssets([]);
  };

  if (analysis) {
    return (
      <ScrollView contentContainerStyle={styles.createScroll} keyboardShouldPersistTaps="handled">
        <View style={styles.hero}>
          <BabyTiger size={56} expression="excited" style={styles.heroEmoji} />
          <Text style={[styles.heroTitle, { color: colors.textPrimary }]}>Review your app idea</Text>
        </View>

        <ReverseFindings re={analysis.reverse_engineering} />

        <Text style={[styles.reviewLabel, { color: colors.textTertiary }]}>APP NAME</Text>
        <TextInput
          value={analysis.suggested_name}
          onChangeText={(text) => setAnalysis({ ...analysis, suggested_name: text })}
          style={[styles.reviewNameInput, { color: colors.textPrimary, backgroundColor: colors.surface, borderColor: colors.border }]}
        />

        <Text style={[styles.reviewLabel, { color: colors.textTertiary }]}>YOUR APP IDEA (EDIT AS YOU LIKE)</Text>
        <TextInput
          value={analysis.raw_idea}
          onChangeText={(text) => setAnalysis({ ...analysis, raw_idea: text })}
          multiline
          numberOfLines={7}
          style={[styles.ideaInput, { color: colors.textPrimary, backgroundColor: colors.surface, borderColor: colors.border }]}
        />

        <View style={styles.reviewButtonRow}>
          <Pressable onPress={reset} style={[styles.secondaryButton, { borderColor: colors.border }]}>
            <RotateCcw size={14} color={colors.textPrimary} />
            <Text style={{ color: colors.textPrimary, fontWeight: "600", fontSize: 13 }}>Start over</Text>
          </Pressable>
          <Pressable
            onPress={handleBuild}
            disabled={isCreating || !analysis.raw_idea.trim()}
            style={[styles.buildButton, { backgroundColor: colors.primary, flex: 1 }, (isCreating || !analysis.raw_idea.trim()) && { opacity: 0.6 }]}
          >
            {isCreating ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <>
                <Sparkles size={14} color="#fff" />
                <Text style={styles.buildButtonText}>Build with Baby Tiger</Text>
              </>
            )}
          </Pressable>
        </View>
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={styles.createScroll} keyboardShouldPersistTaps="handled">
      <View style={styles.hero}>
        <BabyTiger size={56} expression="idle" style={styles.heroEmoji} />
        <Text style={[styles.heroTitle, { color: colors.textPrimary }]}>Rebuild an app you already love</Text>
        <Text style={[styles.heroSubtitle, { color: colors.textSecondary }]}>
          Point Baby Tiger at an existing app — a URL, screenshots, or a description — and get a
          fresh, original app inspired by it.
        </Text>
      </View>

      <View style={styles.sourceTabRow}>
        {SOURCE_TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = sourceType === tab.id;
          return (
            <Pressable
              key={tab.id}
              onPress={() => setSourceType(tab.id)}
              style={[
                styles.sourceTabButton,
                { borderColor: isActive ? colors.primary : colors.border, backgroundColor: isActive ? colors.primaryLight : colors.surface },
              ]}
            >
              <Icon size={14} color={isActive ? colors.primary : colors.textSecondary} />
              <Text style={{ color: isActive ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>
                {tab.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {sourceType === "description" && (
        <TextInput
          value={description}
          onChangeText={setDescription}
          placeholder="e.g. Something like Notion, but focused just on meal planning..."
          placeholderTextColor={colors.textTertiary}
          multiline
          numberOfLines={5}
          style={[styles.ideaInput, { color: colors.textPrimary, backgroundColor: colors.surface, borderColor: colors.border }]}
        />
      )}

      {sourceType === "url" && (
        <TextInput
          value={url}
          onChangeText={setUrl}
          placeholder="https://example.com"
          placeholderTextColor={colors.textTertiary}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          style={[styles.urlInput, { color: colors.textPrimary, backgroundColor: colors.surface, borderColor: colors.border }]}
        />
      )}

      {sourceType === "repo" && (
        <View>
          <TextInput
            value={repoUrl}
            onChangeText={setRepoUrl}
            placeholder="https://github.com/owner/repo"
            placeholderTextColor={colors.textTertiary}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            style={[styles.urlInput, { color: colors.textPrimary, backgroundColor: colors.surface, borderColor: colors.border }]}
          />
          <Text style={{ color: colors.textTertiary, fontSize: 12, marginTop: 8 }}>
            Public repos only. Baby Tiger scans real source files — routes, models, dependencies — not just the README.
          </Text>
        </View>
      )}

      {sourceType === "screenshots" && (
        <View>
          <Pressable
            onPress={addScreenshot}
            style={[styles.screenshotPicker, { borderColor: colors.border, backgroundColor: colors.surface }]}
          >
            <ImagePlus size={22} color={colors.textTertiary} />
            <Text style={{ color: colors.textTertiary, fontSize: 13, fontWeight: "600", marginTop: 6 }}>
              Add a screenshot ({assets.length}/{MAX_SCREENSHOTS})
            </Text>
          </Pressable>

          {assets.length > 0 && (
            <View style={styles.screenshotThumbRow}>
              {assets.map((asset, i) => (
                <View key={`${asset.uri}-${i}`} style={styles.screenshotThumbWrap}>
                  <Image source={{ uri: asset.uri }} style={styles.screenshotThumb} />
                  <Pressable
                    onPress={() => removeScreenshot(i)}
                    style={[styles.screenshotRemove, { backgroundColor: colors.background }]}
                  >
                    <X size={12} color={colors.textPrimary} />
                  </Pressable>
                </View>
              ))}
            </View>
          )}
        </View>
      )}

      <Pressable
        onPress={handleAnalyze}
        disabled={isAnalyzing}
        style={[styles.buildButton, { backgroundColor: colors.primary, marginTop: 16 }, isAnalyzing && { opacity: 0.6 }]}
      >
        {isAnalyzing ? (
          <ActivityIndicator color="#fff" size="small" />
        ) : (
          <>
            <Sparkles size={14} color="#fff" />
            <Text style={styles.buildButtonText}>Analyze &amp; Suggest an App</Text>
          </>
        )}
      </Pressable>
    </ScrollView>
  );
}

/** Shows the REAL facts Baby Tiger extracted (tech stack, pages/files scanned,
 * data entities, endpoints, code snippets pulled) — not the AI-written idea
 * paragraph, which is edited separately below. Renders nothing for
 * description mode since there's nothing to extract from free text. */
function ReverseFindings({ re }: { re: ReverseEngineering }) {
  const { colors } = useTheme();
  if (!re || re.mode === "description") return null;

  const techNames = (re.tech_stack || []).map((t) => t.name);
  const snippetCount = re.code_snippets?.length || 0;

  const scopeLine =
    re.mode === "url"
      ? `${re.pages_crawled ?? 0} real page${(re.pages_crawled ?? 0) === 1 ? "" : "s"} crawled`
      : re.mode === "repo"
      ? `${re.files_scanned ?? 0} real source file${re.files_scanned === 1 ? "" : "s"} scanned in ${re.repo}`
      : re.mode === "screenshots"
      ? "Screens analyzed with vision AI"
      : "";

  if (!scopeLine && techNames.length === 0) return null;

  return (
    <View style={[styles.findingsCard, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 }}>
        <Wrench size={14} color={colors.primary} />
        <Text style={{ color: colors.textPrimary, fontSize: 13, fontWeight: "700" }}>What Baby Tiger actually found</Text>
      </View>
      {scopeLine ? <Text style={{ color: colors.textSecondary, fontSize: 12, marginBottom: 6 }}>{scopeLine}</Text> : null}
      {techNames.length > 0 && (
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 6 }}>
          {techNames.map((name) => (
            <View key={name} style={[styles.findingsChip, { backgroundColor: colors.primaryLight }]}>
              <Text style={{ color: colors.primary, fontSize: 11, fontWeight: "600" }}>{name}</Text>
            </View>
          ))}
        </View>
      )}
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 12 }}>
        {re.data_model && re.data_model.length > 0 && (
          <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{re.data_model.length} data entities found</Text>
        )}
        {re.api_endpoints && re.api_endpoints.length > 0 && (
          <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{re.api_endpoints.length} real endpoints found</Text>
        )}
        {snippetCount > 0 && (
          <Text style={{ color: colors.textTertiary, fontSize: 11 }}>
            {snippetCount} real source file{snippetCount === 1 ? "" : "s"} pulled
          </Text>
        )}
      </View>
    </View>
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
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  scanButton: { flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 6 },
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
  buildButton: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingHorizontal: 16, paddingVertical: 10, borderRadius: 12 },
  buildButtonText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  inspirationLabel: { fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginBottom: 10 },
  exampleCard: { borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 8 },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32 },
  emptyTitle: { fontSize: 16, fontWeight: "700", marginBottom: 4 },
  emptySubtitle: { fontSize: 13, textAlign: "center" },
  listContent: { padding: 16 },
  sourceTabRow: { flexDirection: "row", gap: 8, marginBottom: 14 },
  sourceTabButton: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderWidth: 1, borderRadius: 12, paddingVertical: 10 },
  urlInput: { borderWidth: 1, borderRadius: 16, padding: 14, fontSize: 14, minHeight: 48 },
  screenshotPicker: { borderWidth: 1, borderStyle: "dashed", borderRadius: 16, paddingVertical: 24, alignItems: "center", justifyContent: "center" },
  screenshotThumbRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 10 },
  screenshotThumbWrap: { position: "relative" },
  screenshotThumb: { width: 64, height: 64, borderRadius: 10 },
  screenshotRemove: { position: "absolute", top: -6, right: -6, borderRadius: 999, padding: 3 },
  findingsCard: { borderWidth: 1, borderRadius: 16, padding: 14, marginBottom: 14 },
  findingsChip: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  reviewLabel: { fontSize: 11, fontWeight: "700", letterSpacing: 0.5, marginBottom: 6, marginTop: 4 },
  reviewNameInput: { borderWidth: 1, borderRadius: 12, padding: 12, fontSize: 14, fontWeight: "600", marginBottom: 16 },
  reviewButtonRow: { flexDirection: "row", gap: 10, marginTop: 16 },
  secondaryButton: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderWidth: 1, borderRadius: 12, paddingHorizontal: 16, paddingVertical: 10 },
});
