import { NavLink, useNavigate } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";
import { motion } from "framer-motion";
import {
  Plus,
  Clock,
  CheckCircle2,
  Store,
  Code2,
  Settings,
  ChevronLeft,
  ChevronRight,
  LogOut,
} from "lucide-react";

import { AppDispatch, RootState } from "@/store";
import { toggleSidebar, setActiveTab } from "@/store/slices/uiSlice";
import { logoutUser } from "@/store/slices/authSlice";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

interface NavItem {
  id: string;
  label: string;
  icon: React.ElementType;
  tab?: "create" | "pending" | "completed";
  path?: string;
  badge?: number;
}

export default function Sidebar() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { sidebarCollapsed, activeTab } = useSelector((state: RootState) => state.ui);
  const { user } = useSelector((state: RootState) => state.auth);
  const { projects } = useSelector((state: RootState) => state.project);

  const pendingCount = projects.filter((p) => p.status === "in_progress").length;
  const completedCount = projects.filter((p) => p.status === "completed").length;

  const homeItems: NavItem[] = [
    { id: "create", label: "Create", icon: Plus, tab: "create" },
    { id: "pending", label: "Pending", icon: Clock, tab: "pending", badge: pendingCount || undefined },
    { id: "completed", label: "Completed", icon: CheckCircle2, tab: "completed", badge: completedCount || undefined },
  ];

  const otherItems: NavItem[] = [
    { id: "marketplace", label: "Marketplace", icon: Store, path: "/marketplace" },
    { id: "api-builder", label: "API Builder", icon: Code2, path: "/api-builder" },
  ];

  const handleHomeItemClick = (item: NavItem) => {
    if (item.tab) {
      dispatch(setActiveTab(item.tab));
      navigate("/home");
    }
  };

  const handleLogout = async () => {
    await dispatch(logoutUser());
    navigate("/login", { replace: true });
  };

  return (
    <motion.aside
      initial={false}
      animate={{ width: sidebarCollapsed ? 76 : 240 }}
      transition={{ duration: 0.2, ease: "easeInOut" }}
      className="h-full flex flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)] overflow-hidden"
    >
      {/* Logo + Baby Tiger */}
      <div className="flex items-center gap-2 px-4 py-5 border-b border-[var(--color-border)]">
        <BabyTiger size={36} expression="idle" />
        {!sidebarCollapsed && (
          <motion.span
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="font-bold text-lg text-[var(--color-text-primary)] whitespace-nowrap"
          >
            VengaiCode
          </motion.span>
        )}
      </div>

      {/* Home section */}
      <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
        {!sidebarCollapsed && (
          <p className="px-3 text-xs font-semibold text-[var(--color-text-tertiary)] uppercase tracking-wider mb-2">
            Workspace
          </p>
        )}
        {homeItems.map((item) => {
          const isActive = item.tab === activeTab && location.pathname === "/home";
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              onClick={() => handleHomeItemClick(item)}
              title={sidebarCollapsed ? item.label : undefined}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors relative ${
                isActive
                  ? "bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                  : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)] hover:text-[var(--color-text-primary)]"
              }`}
            >
              <Icon className="w-5 h-5 flex-shrink-0" />
              {!sidebarCollapsed && <span className="flex-1 text-left">{item.label}</span>}
              {item.badge !== undefined && (
                <span
                  className={`flex-shrink-0 text-xs font-semibold rounded-full px-1.5 py-0.5 min-w-[20px] text-center ${
                    isActive
                      ? "bg-[var(--color-primary)] text-white"
                      : "bg-[var(--color-surface-raised)] text-[var(--color-text-secondary)]"
                  } ${sidebarCollapsed ? "absolute -top-1 -right-1" : ""}`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}

        {!sidebarCollapsed && (
          <p className="px-3 text-xs font-semibold text-[var(--color-text-tertiary)] uppercase tracking-wider mb-2 mt-6">
            More
          </p>
        )}
        {otherItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.id}
              to={item.path?.startsWith("http") ? "#" : item.path || "#"}
              onClick={(e) => {
                if (item.path?.startsWith("http")) {
                  e.preventDefault();
                  // External marketplace link — open in default browser via Tauri shell
                  window.open(item.path, "_blank");
                }
              }}
              title={sidebarCollapsed ? item.label : undefined}
              className={({ isActive }) =>
                `w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                    : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)] hover:text-[var(--color-text-primary)]"
                }`
              }
            >
              <Icon className="w-5 h-5 flex-shrink-0" />
              {!sidebarCollapsed && <span>{item.label}</span>}
            </NavLink>
          );
        })}
      </nav>

      {/* Bottom — user, settings, collapse, logout */}
      <div className="border-t border-[var(--color-border)] p-2 space-y-1">
        <NavLink
          to="/settings"
          title={sidebarCollapsed ? "Settings" : undefined}
          className={({ isActive }) =>
            `w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${
              isActive
                ? "bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)] hover:text-[var(--color-text-primary)]"
            }`
          }
        >
          <Settings className="w-5 h-5 flex-shrink-0" />
          {!sidebarCollapsed && <span>Settings</span>}
        </NavLink>

        <button
          onClick={handleLogout}
          title={sidebarCollapsed ? "Logout" : undefined}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium text-[var(--color-text-secondary)] hover:bg-[var(--color-error-light)] hover:text-[var(--color-error)] transition-colors"
        >
          <LogOut className="w-5 h-5 flex-shrink-0" />
          {!sidebarCollapsed && <span>Logout</span>}
        </button>

        {/* Collapse toggle */}
        <button
          onClick={() => dispatch(toggleSidebar())}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl text-xs font-medium text-[var(--color-text-tertiary)] hover:bg-[var(--color-surface-raised)] hover:text-[var(--color-text-primary)] transition-colors mt-1"
        >
          {sidebarCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          {!sidebarCollapsed && <span>Collapse</span>}
        </button>

        {/* User info */}
        {!sidebarCollapsed && user && (
          <div className="flex items-center gap-2 px-3 py-2 mt-1">
            <div className="w-8 h-8 rounded-full bg-[var(--color-primary-light)] flex items-center justify-center text-[var(--color-primary)] font-semibold text-sm flex-shrink-0">
              {user.full_name.charAt(0).toUpperCase()}
            </div>
            <div className="overflow-hidden">
              <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">
                {user.full_name}
              </p>
              <p className="text-xs text-[var(--color-text-tertiary)] capitalize">
                {user.tier} tier
              </p>
            </div>
          </div>
        )}
      </div>
    </motion.aside>
  );
}
