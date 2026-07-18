import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Loader2, Rocket } from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

const CATEGORIES = [
  { value: "productivity", label: "Productivity" },
  { value: "developer_tools", label: "Developer Tools" },
  { value: "business", label: "Business" },
  { value: "education", label: "Education" },
  { value: "games", label: "Games" },
  { value: "social", label: "Social" },
  { value: "finance", label: "Finance" },
  { value: "health", label: "Health" },
  { value: "other", label: "Other" },
];

export default function MarketplaceCreateListingScreen() {
  const navigate = useNavigate();

  const [name, setName] = useState("");
  const [tagline, setTagline] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("other");
  const [techStack, setTechStack] = useState("");
  const [price, setPrice] = useState("0");
  const [iconUrl, setIconUrl] = useState("");
  const [externalUrl, setExternalUrl] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const handleSubmit = async (publish: boolean) => {
    if (!name.trim() || !tagline.trim() || !description.trim()) {
      toast.error("Name, tagline, and description are required.");
      return;
    }

    setIsSaving(true);
    try {
      const { data } = await apiClient.post("/marketplace/apps", {
        name: name.trim(),
        tagline: tagline.trim(),
        description: description.trim(),
        category,
        tech_stack: techStack
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        price: Number(price) || 0,
        icon_url: iconUrl.trim() || undefined,
        external_url: externalUrl.trim() || undefined,
      });

      if (publish) {
        await apiClient.put(`/marketplace/apps/${data.listing.id}`, {
          status: "published",
        });
      }

      toast.success(publish ? "Listing published! 🎉" : "Draft saved 🐯");
      navigate(`/marketplace/apps/${data.listing.id}`);
    } catch (error: any) {
      toast.error(error.message || "Failed to create listing.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--color-background)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <button
          onClick={() => navigate("/marketplace")}
          className="p-2 rounded-lg hover:bg-[var(--color-surface-raised)] transition-colors"
        >
          <ArrowLeft className="w-4 h-4 text-[var(--color-text-secondary)]" />
        </button>
        <BabyTiger size={36} expression="happy" />
        <div className="flex-1">
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">
            New Listing
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            List your app on the VengaiCode marketplace
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-2xl mx-auto rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 space-y-4"
        >
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
              App name *
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. TaskFlow Pro"
              className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
              Tagline *
            </label>
            <input
              value={tagline}
              onChange={(e) => setTagline(e.target.value)}
              placeholder="1 short line describing the app"
              className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
              Description *
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this app do? Who is it for?"
              className="w-full h-32 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)] resize-y"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                Category
              </label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
              >
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                Price (₹, 0 = free)
              </label>
              <input
                type="number"
                min="0"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
              Tech stack (comma-separated)
            </label>
            <input
              value={techStack}
              onChange={(e) => setTechStack(e.target.value)}
              placeholder="React, FastAPI, PostgreSQL"
              className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
              Icon URL (optional)
            </label>
            <input
              value={iconUrl}
              onChange={(e) => setIconUrl(e.target.value)}
              placeholder="https://..."
              className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
              App / demo / repo link (optional)
            </label>
            <input
              value={externalUrl}
              onChange={(e) => setExternalUrl(e.target.value)}
              placeholder="https://..."
              className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
            />
          </div>

          <div className="flex gap-3 pt-2">
            <button
              onClick={() => handleSubmit(false)}
              disabled={isSaving}
              className="flex-1 py-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-primary)] font-semibold text-sm hover:bg-[var(--color-surface)] transition-colors disabled:opacity-60"
            >
              Save as Draft
            </button>
            <button
              onClick={() => handleSubmit(true)}
              disabled={isSaving}
              className="flex-1 py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
            >
              {isSaving ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Rocket className="w-4 h-4" />
              )}
              Publish
            </button>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
