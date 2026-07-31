import { useEffect, useState } from "react";
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { Redirect, router } from "expo-router";
import { Search, ShieldCheck, Crown, ChevronLeft, ChevronRight } from "lucide-react-native";

import apiClient from "@/lib/api";
import { useToast } from "@/components/ui/Toast";
import { useAppSelector } from "@/store/hooks";
import { useTheme } from "@/theme/useTheme";

interface AdminUserRow {
  id: string;
  full_name: string;
  username: string;
  email: string;
  tier: string;
  status: string;
  is_admin: boolean;
  is_vip: boolean;
  projects_count: number;
}

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "active", label: "Active" },
  { value: "suspended", label: "Suspended" },
  { value: "banned", label: "Banned" },
];

const PAGE_SIZE = 20;

export default function AdminUsersScreen() {
  const { colors } = useTheme();
  const { showToast } = useToast();
  const isAdmin = useAppSelector((state) => state.auth.user?.is_admin);

  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  const loadUsers = async () => {
    setIsLoading(true);
    try {
      const { data } = await apiClient.get("/admin/users", {
        params: {
          search: search || undefined,
          status: statusFilter || undefined,
          page,
          page_size: PAGE_SIZE,
        },
      });
      setUsers(data.users || []);
      setTotal(data.total || 0);
    } catch (error: any) {
      showToast(error.message || "Failed to load users.", "error");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadUsers();
  }, [page, statusFilter]);

  if (!isAdmin) return <Redirect href="/(app)/(tabs)/home" />;

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const statusColor = (status: string) => {
    if (status === "active") return colors.success;
    if (status === "banned" || status === "suspended") return colors.error;
    return colors.textTertiary;
  };

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <View style={[styles.header, { borderBottomColor: colors.border }]}>
        <Text style={[styles.headerTitle, { color: colors.textPrimary }]}>Admin</Text>
        <Text style={[styles.headerSubtitle, { color: colors.textTertiary }]}>
          {total} user{total === 1 ? "" : "s"}
        </Text>
      </View>

      <View style={styles.filterArea}>
        <View style={[styles.searchRow, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <Search size={16} color={colors.textTertiary} />
          <TextInput
            value={search}
            onChangeText={setSearch}
            onSubmitEditing={() => {
              setPage(1);
              loadUsers();
            }}
            placeholder="Search name, username, or email..."
            placeholderTextColor={colors.textTertiary}
            style={[styles.searchInput, { color: colors.textPrimary }]}
          />
        </View>
        <View style={styles.chipRow}>
          {STATUS_FILTERS.map((f) => {
            const selected = statusFilter === f.value;
            return (
              <Pressable
                key={f.value}
                onPress={() => {
                  setStatusFilter(f.value);
                  setPage(1);
                }}
                style={[
                  styles.chip,
                  {
                    borderColor: selected ? colors.primary : colors.border,
                    backgroundColor: selected ? colors.primaryLight : colors.surface,
                  },
                ]}
              >
                <Text style={{ color: selected ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>
                  {f.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>

      {isLoading && users.length === 0 ? (
        <View style={styles.centered}>
          <ActivityIndicator size="large" color={colors.primary} />
        </View>
      ) : users.length === 0 ? (
        <View style={styles.centered}>
          <Text style={{ color: colors.textTertiary, fontSize: 13 }}>No users match this filter.</Text>
        </View>
      ) : (
        <FlatList
          data={users}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.listContent}
          renderItem={({ item }) => (
            <Pressable
              onPress={() => router.push(`/(app)/admin/users/${item.id}` as any)}
              style={[styles.row, { borderColor: colors.border, backgroundColor: colors.surface }]}
            >
              <View style={[styles.avatar, { backgroundColor: colors.primaryLight }]}>
                <Text style={{ color: colors.primary, fontWeight: "700" }}>
                  {item.full_name.charAt(0).toUpperCase()}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 5 }}>
                  <Text style={[styles.name, { color: colors.textPrimary }]} numberOfLines={1}>
                    {item.full_name}
                  </Text>
                  {item.is_admin && <ShieldCheck size={12} color={colors.primary} />}
                  {item.is_vip && <Crown size={12} color={colors.primary} />}
                </View>
                <Text style={[styles.meta, { color: colors.textTertiary }]} numberOfLines={1}>
                  {item.email} · {item.projects_count} project{item.projects_count === 1 ? "" : "s"}
                </Text>
              </View>
              <Text style={{ color: statusColor(item.status), fontSize: 11, fontWeight: "700", textTransform: "capitalize" }}>
                {item.status.replace("_", " ")}
              </Text>
            </Pressable>
          )}
          ListFooterComponent={
            total > PAGE_SIZE ? (
              <View style={styles.pagination}>
                <Pressable onPress={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} hitSlop={8}>
                  <ChevronLeft size={18} color={page <= 1 ? colors.textTertiary : colors.textPrimary} />
                </Pressable>
                <Text style={{ color: colors.textTertiary, fontSize: 12 }}>
                  Page {page} of {totalPages}
                </Text>
                <Pressable onPress={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} hitSlop={8}>
                  <ChevronRight size={18} color={page >= totalPages ? colors.textTertiary : colors.textPrimary} />
                </Pressable>
              </View>
            ) : null
          }
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  header: { padding: 20, borderBottomWidth: StyleSheet.hairlineWidth },
  headerTitle: { fontSize: 20, fontWeight: "700" },
  headerSubtitle: { fontSize: 12, marginTop: 2 },
  filterArea: { padding: 16, gap: 10 },
  searchRow: { flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10 },
  searchInput: { flex: 1, fontSize: 13, padding: 0 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6 },
  centered: { flex: 1, alignItems: "center", justifyContent: "center", padding: 32 },
  listContent: { paddingHorizontal: 16, paddingBottom: 24, gap: 8 },
  row: { flexDirection: "row", alignItems: "center", gap: 10, borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 8 },
  avatar: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  name: { fontSize: 14, fontWeight: "600", flexShrink: 1 },
  meta: { fontSize: 11, marginTop: 1 },
  pagination: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 16, paddingVertical: 16 },
});
