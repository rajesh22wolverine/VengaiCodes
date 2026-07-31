import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Crown, ShieldCheck, Loader2 } from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

interface AdminUser {
  id: string;
  full_name: string;
  username: string;
  email: string;
  mobile?: string | null;
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
  category: string;
  platforms: string[];
  is_published: boolean;
  created_at: string;
  updated_at: string;
}

interface AdminAction {
  id: string;
  admin_id: string;
  action_type: string;
  reason: string;
  created_at: string;
}

const STATUS_OPTIONS = [
  { value: "active", label: "Active (unban / unsuspend)" },
  { value: "warned", label: "Warned" },
  { value: "suspended", label: "Suspended (temporary block)" },
  { value: "banned", label: "Banned (permanent block)" },
];

const STATUS_STYLES: Record<string, string> = {
  active: "bg-[var(--color-success-light)] text-[var(--color-success)]",
  warned: "bg-[var(--color-warning-light)] text-[var(--color-warning)]",
  suspended: "bg-[var(--color-warning-light)] text-[var(--color-warning)]",
  banned: "bg-[var(--color-error-light)] text-[var(--color-error)]",
  pending_verification: "bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)]",
};

export default function AdminUserDetailScreen() {
  const { userId } = useParams();
  const navigate = useNavigate();

  const [user, setUser] = useState<AdminUser | null>(null);
  const [projects, setProjects] = useState<AdminProject[]>([]);
  const [recentActions, setRecentActions] = useState<AdminAction[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const [newStatus, setNewStatus] = useState("active");
  const [reason, setReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    loadDetail();
  }, [userId]);

  const loadDetail = async () => {
    setIsLoading(true);
    try {
      const { data } = await apiClient.get(`/admin/users/${userId}`);
      setUser(data.user);
      setProjects(data.projects || []);
      setRecentActions(data.recent_actions || []);
      setNewStatus(data.user.status);
    } catch (error: any) {
      toast.error(error.message || "User not found.");
      navigate("/admin");
    } finally {
      setIsLoading(false);
    }
  };

  const handleApplyStatus = async () => {
    if (!user) return;
    if (reason.trim().length < 3) {
      toast.error("Please give a reason (at least 3 characters) for this action.");
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
      toast.success("User status updated.");
      loadDetail();
    } catch (error: any) {
      toast.error(error.message || "Failed to update user status.");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 bg-[var(--color-background)]">
        <BabyTiger size={100} expression="thinking" />
        <p className="text-[var(--color-text-secondary)] text-sm">Loading...</p>
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--color-background)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <button
          onClick={() => navigate("/admin")}
          className="p-2 rounded-lg hover:bg-[var(--color-surface-raised)] transition-colors"
        >
          <ArrowLeft className="w-4 h-4 text-[var(--color-text-secondary)]" />
        </button>
        <BabyTiger size={36} expression="idle" />
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">
              {user.full_name}
            </h1>
            {user.is_admin && <ShieldCheck className="w-3.5 h-3.5 text-[var(--color-primary)]" aria-label="Admin" />}
            {user.is_vip && <Crown className="w-3.5 h-3.5 text-[var(--color-warning)]" aria-label="VIP" />}
          </div>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            {user.email} · @{user.username}
          </p>
        </div>
        <span
          className={`text-xs font-medium px-2.5 py-1 rounded-full flex-shrink-0 ${
            STATUS_STYLES[user.status] || "bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)]"
          }`}
        >
          {user.status.replace("_", " ")}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-6">
          {/* Profile summary */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 grid grid-cols-2 sm:grid-cols-4 gap-4"
          >
            <div>
              <p className="text-xs text-[var(--color-text-tertiary)]">Tier</p>
              <p className="text-sm font-medium text-[var(--color-text-primary)] capitalize">{user.tier}</p>
            </div>
            <div>
              <p className="text-xs text-[var(--color-text-tertiary)]">Restriction</p>
              <p className="text-sm font-medium text-[var(--color-text-primary)] capitalize">
                {user.restriction_level.replace(/_/g, " ")}
              </p>
            </div>
            <div>
              <p className="text-xs text-[var(--color-text-tertiary)]">Joined</p>
              <p className="text-sm font-medium text-[var(--color-text-primary)]">
                {new Date(user.created_at).toLocaleDateString()}
              </p>
            </div>
            <div>
              <p className="text-xs text-[var(--color-text-tertiary)]">Last login</p>
              <p className="text-sm font-medium text-[var(--color-text-primary)]">
                {user.last_login ? new Date(user.last_login).toLocaleDateString() : "Never"}
              </p>
            </div>
          </motion.div>

          {/* Projects */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 }}
            className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
          >
            <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-3">
              Projects ({projects.length})
            </h2>
            {projects.length === 0 ? (
              <p className="text-xs text-[var(--color-text-tertiary)]">No projects yet.</p>
            ) : (
              <div className="space-y-2">
                {projects.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center gap-3 rounded-xl border border-[var(--color-border)] px-3 py-2.5"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">{p.name}</p>
                      <p className="text-xs text-[var(--color-text-tertiary)] capitalize">
                        {p.current_phase.replace("_", " ")} · {Math.round(p.progress_percent)}%
                      </p>
                    </div>
                    <span
                      className={`text-xs font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${
                        p.status === "completed"
                          ? "bg-[var(--color-success-light)] text-[var(--color-success)]"
                          : p.status === "in_progress"
                          ? "bg-[var(--color-info-light)] text-[var(--color-info)]"
                          : "bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)]"
                      }`}
                    >
                      {p.status.replace("_", " ")}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </motion.div>

          {/* Take action */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
          >
            <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-3">Take action</h2>
            <div className="space-y-3">
              <select
                value={newStatus}
                onChange={(e) => setNewStatus(e.target.value)}
                className="w-full px-3 py-2.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] text-sm text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-primary)]"
              >
                {STATUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Reason for this action (required, logged to the audit trail)..."
                rows={2}
                className="w-full px-3 py-2.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none focus:border-[var(--color-primary)] resize-none"
              />
              <button
                onClick={handleApplyStatus}
                disabled={isSubmitting || newStatus === user.status}
                className="px-4 py-2.5 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {isSubmitting && <Loader2 className="w-4 h-4 animate-spin" />}
                Apply
              </button>
            </div>
          </motion.div>

          {/* Recent admin actions */}
          {recentActions.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 }}
              className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
            >
              <h2 className="text-sm font-semibold text-[var(--color-text-primary)] mb-3">Recent admin actions</h2>
              <div className="space-y-2">
                {recentActions.map((a) => (
                  <div key={a.id} className="text-xs border-b border-[var(--color-border)] pb-2 last:border-0">
                    <p className="text-[var(--color-text-primary)] font-medium capitalize">
                      {a.action_type.replace(/,/g, ", ").replace(/_/g, " ")}
                    </p>
                    <p className="text-[var(--color-text-tertiary)]">{a.reason}</p>
                    <p className="text-[var(--color-text-tertiary)]">
                      {new Date(a.created_at).toLocaleString()}
                    </p>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </div>
      </div>
    </div>
  );
}
