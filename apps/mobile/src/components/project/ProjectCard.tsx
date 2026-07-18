import { Pressable, StyleSheet, Text, View } from "react-native";
import { router } from "expo-router";
import { Globe, Monitor, Smartphone, Trash2 } from "lucide-react-native";

import { Project, SDLCPhase } from "@/store/slices/projectSlice";
import { useTheme } from "@/theme/useTheme";

const PHASE_LABELS: Record<SDLCPhase, string> = {
  requirements: "Requirements",
  uiux: "UI/UX Design",
  architecture: "Architecture",
  api_builder: "API Builder",
  code_generation: "Code Generation",
  testing: "Testing",
  export: "Export",
  completed: "Completed",
};

const PHASE_ROUTES: Record<SDLCPhase, string> = {
  requirements: "wizard",
  uiux: "uiux",
  architecture: "architecture",
  api_builder: "architecture",
  code_generation: "codegen",
  testing: "testing",
  export: "export",
  completed: "export",
};

const PLATFORM_ICONS: Record<string, React.ElementType> = {
  web: Globe,
  mobile_ios: Smartphone,
  mobile_android: Smartphone,
  desktop_windows: Monitor,
  desktop_mac: Monitor,
  desktop_linux: Monitor,
};

interface ProjectCardProps {
  project: Project;
  onDelete?: (id: string) => void;
}

export default function ProjectCard({ project, onDelete }: ProjectCardProps) {
  const { colors } = useTheme();

  const handleOpen = () => {
    const route = PHASE_ROUTES[project.current_phase] || "wizard";
    router.push(`/(app)/project/${project.id}/${route}` as any);
  };

  const statusLabel =
    project.status === "in_progress" ? "In Progress" : project.status === "completed" ? "Completed" : "Draft";
  const statusColor = project.status === "completed" ? colors.success : project.status === "in_progress" ? colors.primary : colors.textTertiary;

  return (
    <Pressable
      onPress={handleOpen}
      style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}
    >
      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.title, { color: colors.textPrimary }]} numberOfLines={1}>
            {project.name}
          </Text>
          {project.description ? (
            <Text style={[styles.description, { color: colors.textTertiary }]} numberOfLines={2}>
              {project.description}
            </Text>
          ) : null}
        </View>
        {onDelete && (
          <Pressable onPress={() => onDelete(project.id)} hitSlop={8}>
            <Trash2 size={16} color={colors.textTertiary} />
          </Pressable>
        )}
      </View>

      {project.platforms?.length > 0 && (
        <View style={styles.platformRow}>
          {project.platforms.map((platform) => {
            const Icon = PLATFORM_ICONS[platform] || Globe;
            return (
              <View key={platform} style={[styles.platformIcon, { backgroundColor: colors.background }]}>
                <Icon size={13} color={colors.textSecondary} />
              </View>
            );
          })}
        </View>
      )}

      <View style={styles.progressSection}>
        <View style={styles.progressLabelRow}>
          <Text style={[styles.progressLabel, { color: colors.textSecondary }]}>
            {PHASE_LABELS[project.current_phase]}
          </Text>
          <Text style={[styles.progressPercent, { color: colors.primary }]}>
            {Math.round(project.progress_percent)}%
          </Text>
        </View>
        <View style={[styles.progressTrack, { backgroundColor: colors.background }]}>
          <View style={[styles.progressFill, { width: `${project.progress_percent}%`, backgroundColor: colors.primary }]} />
        </View>
      </View>

      <View style={styles.footerRow}>
        <View style={[styles.statusBadge, { backgroundColor: colors.background }]}>
          <Text style={[styles.statusText, { color: statusColor }]}>{statusLabel}</Text>
        </View>
        <Text style={[styles.dateText, { color: colors.textTertiary }]}>
          {new Date(project.updated_at).toLocaleDateString()}
        </Text>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 14, padding: 14, marginBottom: 12 },
  headerRow: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 10 },
  title: { fontSize: 15, fontWeight: "700" },
  description: { fontSize: 12, marginTop: 2 },
  platformRow: { flexDirection: "row", gap: 6, marginBottom: 10 },
  platformIcon: { width: 24, height: 24, borderRadius: 6, alignItems: "center", justifyContent: "center" },
  progressSection: { marginBottom: 8 },
  progressLabelRow: { flexDirection: "row", justifyContent: "space-between", marginBottom: 4 },
  progressLabel: { fontSize: 12, fontWeight: "500" },
  progressPercent: { fontSize: 12, fontWeight: "700" },
  progressTrack: { height: 6, borderRadius: 3, overflow: "hidden" },
  progressFill: { height: "100%", borderRadius: 3 },
  footerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  statusBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999 },
  statusText: { fontSize: 11, fontWeight: "600" },
  dateText: { fontSize: 11 },
});
