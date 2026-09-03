import { useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Sparkles, Loader2 } from "lucide-react";
import toast from "react-hot-toast";

import { AppDispatch, RootState } from "@/store";
import { createProject } from "@/store/slices/projectSlice";
import { setTigerExpression } from "@/store/slices/uiSlice";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

const EXAMPLE_IDEAS = [
  "A food delivery app like Swiggy but only for home cooks",
  "A habit tracker that celebrates streaks with animations",
  "A marketplace for renting out unused parking spots",
  "An app like Instagram but for sharing recipes with cooking steps",
];

export default function CreateTab() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { isLoading } = useSelector((state: RootState) => state.project);
  const { user } = useSelector((state: RootState) => state.auth);
  const [idea, setIdea] = useState("");

  const canCreate = user ? user.projects_remaining > 0 : true;

  const handleSubmit = async () => {
    if (!idea.trim()) {
      toast.error("Tell Baby Tiger what you want to build first! 🐯");
      return;
    }
    if (!canCreate) {
      toast.error("You've used all your free projects. Upgrade to create more! 🐯");
      return;
    }

    dispatch(setTigerExpression("thinking"));

    // Use first ~50 chars of idea as a working project name —
    // AI will suggest a better name during the requirements wizard
    const name = idea.trim().slice(0, 50);

    const result = await dispatch(createProject({ name, rawIdea: idea.trim() }));

    if (createProject.fulfilled.match(result)) {
      dispatch(setTigerExpression("excited"));
      toast.success("Let's understand your idea! 🐯");
      navigate(`/project/${result.payload.id}/wizard`);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-2xl mx-auto pt-8">
        {/* Hero */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-center mb-8"
        >
          <div className="flex justify-center mb-4">
            <BabyTiger size={100} expression="excited" />
          </div>
          <h2 className="text-2xl font-bold text-[var(--color-text-primary)] mb-2">
            What do you want to build today?
          </h2>
          <p className="text-[var(--color-text-secondary)]">
            Describe your idea in plain English. Baby Tiger will ask a few
            smart questions, then build your complete app — Web, Mobile,
            Desktop — in under 30 minutes.
          </p>
        </motion.div>

        {/* Idea input */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="mb-4"
        >
          <textarea
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            placeholder="e.g. I want a food delivery app like Swiggy but only for home cooks in my neighbourhood..."
            rows={5}
            className="w-full px-4 py-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none transition-all resize-none text-sm leading-relaxed"
          />

          <div className="flex items-center justify-between mt-3">
            <div className="text-xs text-[var(--color-text-tertiary)] space-y-0.5">
              {user && (
                <>
                  <p>
                    {user.projects_remaining === -1 || user.projects_limit === -1
                      ? "Unlimited projects available"
                      : `${user.projects_remaining} of ${user.projects_limit} project${user.projects_limit === 1 ? "" : "s"} remaining`}
                  </p>
                  <p>
                    {user.ai_tokens_limit === -1
                      ? "Unlimited AI tokens available"
                      : `${user.ai_tokens_remaining.toLocaleString()} of ${user.ai_tokens_limit.toLocaleString()} AI tokens remaining`}
                  </p>
                </>
              )}
            </div>
            <button
              onClick={handleSubmit}
              disabled={isLoading || !idea.trim()}
              className="px-5 py-2.5 rounded-xl bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-white font-semibold text-sm transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-2 shadow-md hover:shadow-lg"
            >
              {isLoading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Starting...
                </>
              ) : (
                <>
                  <Sparkles className="w-4 h-4" />
                  Build with Baby Tiger
                </>
              )}
            </button>
          </div>
        </motion.div>

        {/* Example ideas */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          <p className="text-xs font-semibold text-[var(--color-text-tertiary)] uppercase tracking-wider mb-3">
            Need inspiration?
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {EXAMPLE_IDEAS.map((example) => (
              <button
                key={example}
                onClick={() => setIdea(example)}
                className="text-left text-sm px-4 py-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)] hover:border-[var(--color-primary)] hover:text-[var(--color-text-primary)] transition-colors"
              >
                {example}
              </button>
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
