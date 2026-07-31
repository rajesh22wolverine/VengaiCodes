import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { Redirect, router, useLocalSearchParams } from "expo-router";
import { ShieldCheck, Crown } from "lucide-react-native";

import apiClient from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import ScreenContainer from "@/components/ui/ScreenContainer";
import { useAppSelector } from "@/store/hooks";
import { useTheme } from "@/theme/useTheme";

interface AdminUser {
  id: string;
  full_name: string;
  username: string;
  email: string;
  tier: string;
  is_admin: boolean;
  is_vip: boolean;
  status: string;
  restriction_level: string;
  created_at: string;
  last_login?: string | null;
}

interface AdminProject {
  id: string;
  name: string;
  status: string;
  current_phase: string;
  progress_percent: number;
}

interface AdminAction {
  id: string;
  action_type: string;
  reason: string;
  created_at: string;
}

const STATUS_OPTIONS = [
  { value: "active", label: "Active" },
  { value: "warned", label: "Warned" },
  { value: "suspended", label: "Suspended" },
  { value: "banned", label: "Banned" },
];

export default function AdminUserDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();
  const isAdmin = useAppSelector((state) => state.auth.user?.is_admin);

  const [user, setUser] = useState<AdminUser | null>(null);
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [recentActions, setRecentActions] = useState<AdminAction[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const [newStatus, setNewStatus] = useState("active");
  const [reason, setReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const loadDetail = async () => {
    setIsLoading(true);
    try {
      const { data } = await apiClient.get(`/admin/users/${id}`);
      setUser(data.user);
      setProjects(data.projects || []);
      setRecentActions(data.recent_actions || []);
      setNewStatus(data.user.status);
    } catch (error: any) {
      showToast(error.message || "User not found.", "error");
      router.back();
    } finally {
      setIsLoading(false);
    }
  };

  const handleApplyStatus = async () => {
    if (!user) return;
    if (reason.trim().length < 3) {
      showToast("Please give a reason (at least 3 characters).", "error");
      return;
    }
    setIsSubmitting(true);
    try {
      const { data } = await apiClient.patch(`/admin/users/${user.id}`, {
        status: newStatus,
        reason: reason.trim(),
      });
      setUser(data.user);
      setReason("");
      showToast("User status updated.");
      loadDetail();
    } catch (error: any) {
      showToast(error.message || "Failed to update user status.", "error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const statusColor = (status: string) => {
    if (status === "active") return colors.success;
    if (status === "banned" || status === "suspended") return colors.error;
    return colors.textTertiary;
  };

  const projectStatusColor = (status: string) => {
    if (status === "completed") return colors.success;
    if (status === "in_progress") return colors.primary;
    return colors.textTertiary;
  };

  useEffect(() => {
    loadDetail();
  }, [id]);

  if (!isAdmin) return <Redirect href="/(app)/(tabs)/home" />;

  if (isLoading) {
    return (
      <View style={[styles.centered, { backgroundColor: colors.background }]}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (!user) return null;

  return (
    <ScreenContainer>
      <View style={styles.headerRow}>
        <Text style={[styles.title, { color: colors.textPrimary }]}>{user.full_name}</Text>
        {user.is_admin && <ShieldCheck size={16} color={colors.primary} />}
        {user.is_vip && <Crown size={16} color={colors.primary} />}
      </View>
      <Text style={[styles.subtitle, { color: colors.textTertiary }]}>
        {user.email} · @{user.username}
      </Text>

      {/* Profile summary */}
      <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <View style={styles.summaryRow}>
          <SummaryField label="Tier" value={user.tier} colors={colors} />
          <SummaryField label="Status" value={user.status.replace("_", " ")} valueColor={statusColor(user.status)} colors={colors} />
        </View>
        <View style={styles.summaryRow}>
          <SummaryField label="Restriction" value={user.restriction_level.replace(/_/g, " ")} colors={colors} />
          <SummaryField label="Joined" value={new Date(user.created_at).toLocaleDateString()} colors={colors} />
        </View>
      </View>

      {/* Projects */}
      <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>Projects ({projects.length})</Text>
        {projects.length === 0 ? (
          <Text style={{ color: colors.textTertiary, fontSize: 12 }}>No projects yet.</Text>
        ) : (
          projects.map((p) => (
            <View key={p.id} style={[styles.projectRow, { borderColor: colors.border }]}>
              <View style={{ flex: 1 }}>
                <Text style={[styles.projectName, { color: colors.textPrimary }]} numberOfLines={1}>
                  {p.name}
                </Text>
                <Text style={{ color: colors.textTertiary, fontSize: 11, textTransform: "capitalize" }}>
                  {p.current_phase.replace("_", " ")} · {Math.round(p.progress_percent)}%
                </Text>
              </View>
              <Text style={{ color: projectStatusColor(p.status), fontSize: 11, fontWeight: "700", textTransform: "capitalize" }}>
                {p.status.replace("_", " ")}
              </Text>
            </View>
          ))
        )}
      </View>

      {/* Take action */}
      <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
        <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>Take action</Text>
        <View style={styles.chipRow}>
          {STATUS_OPTIONS.map((o) => {
            const selected = newStatus === o.value;
            return (
              <Pressable
                key={o.value}
                onPress={() => setNewStatus(o.value)}
                style={[
                  styles.chip,
                  {
                    borderColor: selected ? colors.primary : colors.border,
                    backgroundColor: selected ? colors.primaryLight : colors.background,
                  },
                ]}
              >
                <Text style={{ color: selected ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>
                  {o.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
        <TextInput
          value={reason}
          onChangeText={setReason}
          placeholder="Reason for this action (required, logged to audit trail)..."
          placeholderTextColor={colors.textTertiary}
          multiline
          numberOfLines={2}
          style={[styles.input, { color: colors.textPrimary, backgroundColor: colors.background, borderColor: colors.border }]}
        />
        <Pressable
          onPress={handleApplyStatus}
          disabled={isSubmitting || newStatus === user.status}
          style={[
            styles.applyButton,
            { backgroundColor: colors.primary },
            (isSubmitting || newStatus === user.status) && { opacity: 0.5 },
          ]}
        >
          {isSubmitting ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.applyButtonText}>Apply</Text>}
        </Pressable>
      </View>

      {/* Recent admin actions */}
      {recentActions.length > 0 && (
        <View style={[styles.card, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <Text style={[styles.sectionTitle, { color: colors.textPrimary }]}>Recent admin actions</Text>
          {recentActions.map((a) => (
            <View key={a.id} style={[styles.actionRow, { borderColor: colors.border }]}>
              <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "600", textTransform: "capitalize" }}>
                {a.action_type.replace(/,/g, ", ").replace(/_/g, " ")}
              </Text>
              <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{a.reason}</Text>
              <Text style={{ color: colors.textTertiary, fontSize: 10 }}>{new Date(a.created_at).toLocaleString()}</Text>
            </View>
          ))}
        </View>
      )}
    </ScreenContainer>
  );
}

function SummaryField({
  label,
  value,
  valueColor,
  colors,
}: {
  label: string;
  value: string;
  valueColor?: string;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={{ flex: 1 }}>
      <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{label}</Text>
      <Text style={{ color: valueColor || colors.textPrimary, fontSize: 13, fontWeight: "600", textTransform: "capitalize" }}>
        {value}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  centered: { flex: 1, alignItems: "center", justifyContent: "center" },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { fontSize: 20, fontWeight: "700" },
  subtitle: { fontSize: 12, marginTop: 2, marginBottom: 16 },
  card: { borderWidth: 1, borderRadius: 14, padding: 16, marginBottom: 16, gap: 10 },
  summaryRow: { flexDirection: "row", gap: 16 },
  sectionTitle: { fontSize: 14, fontWeight: "700" },
  projectRow: { flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderRadius: 10, padding: 10 },
  projectName: { fontSize: 13, fontWeight: "600" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 8 },
  input: { borderWidth: 1, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 13, textAlignVertical: "top" },
  applyButton: { borderRadius: 10, paddingVertical: 12, alignItems: "center" },
  applyButtonText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  actionRow: { borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 8, marginTop: 4, gap: 2 },
});
