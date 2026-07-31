import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ShieldCheck, Search, ChevronLeft, ChevronRight, Crown } from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

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
  created_at: string;
}

const STATUS_FILTERS = [
  { value: "", label: "All statuses" },
  { value: "active", label: "Active" },
  { value: "warned", label: "Warned" },
  { value: "suspended", label: "Suspended" },
  { value: "banned", label: "Banned" },
  { value: "pending_verification", label: "Pending verification" },
];

const STATUS_STYLES: Record<string, string> = {
  active: "bg-[var(--color-success-light)] text-[var(--color-success)]",
  warned: "bg-[var(--color-warning-light)] text-[var(--color-warning)]",
  suspended: "bg-[var(--color-warning-light)] text-[var(--color-warning)]",
  banned: "bg-[var(--color-error-light)] text-[var(--color-error)]",
  pending_verification: "bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)]",
};

const PAGE_SIZE = 20;

export default function AdminScreen() {
  const navigate = useNavigate();
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    loadUsers();
  }, [page, statusFilter]);

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
      toast.error(error.message || "Failed to load users.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    loadUsers();
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--color-background)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <BabyTiger size={36} expression="idle" />
        <div className="flex-1">
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">Admin</h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            {total} user{total === 1 ? "" : "s"} — search, review, and moderate accounts
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <div className="flex items-center gap-3">
          <form onSubmit={handleSearchSubmit} className="flex-1 relative">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)]" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by name, username, or email..."
              className="w-full pl-9 pr-3 py-2.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none focus:border-[var(--color-primary)]"
            />
          </form>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            className="px-3 py-2.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] text-sm text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-primary)]"
          >
            {STATUS_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* User list */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center gap-4 py-16">
            <BabyTiger size={80} expression="thinking" />
            <p className="text-[var(--color-text-secondary)] text-sm">Loading users...</p>
          </div>
        ) : users.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16">
            <ShieldCheck className="w-10 h-10 text-[var(--color-text-tertiary)]" />
            <p className="text-[var(--color-text-secondary)] text-sm">No users match this filter.</p>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto space-y-2">
            {users.map((u, i) => (
              <motion.div
                key={u.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.02 }}
                onClick={() => navigate(`/admin/users/${u.id}`)}
                className="cursor-pointer flex items-center gap-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-3 hover:border-[var(--color-primary)] transition-colors"
              >
                <div className="w-9 h-9 rounded-full bg-[var(--color-primary-light)] flex items-center justify-center text-[var(--color-primary)] font-semibold text-sm flex-shrink-0">
                  {u.full_name.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">
                      {u.full_name}
                    </p>
                    {u.is_admin && (
                      <ShieldCheck
                        className="w-3.5 h-3.5 text-[var(--color-primary)] flex-shrink-0"
                        aria-label="Admin"
                      />
                    )}
                    {u.is_vip && (
                      <Crown className="w-3.5 h-3.5 text-[var(--color-warning)] flex-shrink-0" aria-label="VIP" />
                    )}
                  </div>
                  <p className="text-xs text-[var(--color-text-tertiary)] truncate">
                    {u.email} · @{u.username}
                  </p>
                </div>
                <span className="text-xs text-[var(--color-text-secondary)] capitalize flex-shrink-0">
                  {u.tier}
                </span>
                <span className="text-xs text-[var(--color-text-tertiary)] flex-shrink-0">
                  {u.projects_count} project{u.projects_count === 1 ? "" : "s"}
                </span>
                <span
                  className={`text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${
                    STATUS_STYLES[u.status] || "bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)]"
                  }`}
                >
                  {u.status.replace("_", " ")}
                </span>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-center gap-3 px-6 py-3 border-t border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="p-2 rounded-lg hover:bg-[var(--color-surface-raised)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronLeft className="w-4 h-4 text-[var(--color-text-secondary)]" />
          </button>
          <span className="text-xs text-[var(--color-text-tertiary)]">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="p-2 rounded-lg hover:bg-[var(--color-surface-raised)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronRight className="w-4 h-4 text-[var(--color-text-secondary)]" />
          </button>
        </div>
      )}
    </div>
  );
}
