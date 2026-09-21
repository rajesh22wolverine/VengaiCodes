import { useDispatch, useSelector } from "react-redux";
import { motion } from "framer-motion";
import { Plus, RefreshCw, Clock, CheckCircle2 } from "lucide-react";

import { AppDispatch, RootState } from "@/store";
import { setActiveTab } from "@/store/slices/uiSlice";
import TopBar from "@/components/layout/TopBar";
import CreateTab from "./CreateTab";
import ReverseAppTab from "./ReverseAppTab";
import PendingTab from "./PendingTab";
import CompletedTab from "./CompletedTab";

type TabId = "create" | "reverse" | "pending" | "completed";

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: "create", label: "Create", icon: Plus },
  { id: "reverse", label: "Reverse App", icon: RefreshCw },
  { id: "pending", label: "Pending", icon: Clock },
  { id: "completed", label: "Completed", icon: CheckCircle2 },
];

export default function HomeScreen() {
  const dispatch = useDispatch<AppDispatch>();
  const { activeTab } = useSelector((state: RootState) => state.ui);
  const { projects } = useSelector((state: RootState) => state.project);

  const pendingCount = projects.filter(
    (p) => p.status === "draft" || p.status === "in_progress"
  ).length;
  const completedCount = projects.filter((p) => p.status === "completed").length;

  const badgeFor = (tab: TabId) => {
    if (tab === "pending") return pendingCount || undefined;
    if (tab === "completed") return completedCount || undefined;
    return undefined;
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <TopBar title="Dashboard" />

      {/* Tab bar */}
      <div className="flex items-center gap-1 px-6 pt-4 border-b border-[var(--color-border)] flex-shrink-0">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          const badge = badgeFor(tab.id);

          return (
            <button
              key={tab.id}
              onClick={() => dispatch(setActiveTab(tab.id))}
              className="relative px-4 py-2.5 flex items-center gap-2 text-sm font-medium transition-colors"
            >
              <Icon
                className={`w-4 h-4 ${
                  isActive ? "text-[var(--color-primary)]" : "text-[var(--color-text-tertiary)]"
                }`}
              />
              <span
                className={
                  isActive
                    ? "text-[var(--color-primary)]"
                    : "text-[var(--color-text-secondary)]"
                }
              >
                {tab.label}
              </span>
              {badge !== undefined && (
                <span
                  className={`text-xs font-semibold rounded-full px-1.5 py-0.5 min-w-[20px] text-center ${
                    isActive
                      ? "bg-[var(--color-primary)] text-white"
                      : "bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)]"
                  }`}
                >
                  {badge}
                </span>
              )}

              {isActive && (
                <motion.div
                  layoutId="home-tab-indicator"
                  className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full bg-[var(--color-primary)]"
                  transition={{ duration: 0.2 }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {activeTab === "create" && <CreateTab />}
      {activeTab === "reverse" && <ReverseAppTab />}
      {activeTab === "pending" && <PendingTab />}
      {activeTab === "completed" && <CompletedTab />}
    </div>
  );
}
