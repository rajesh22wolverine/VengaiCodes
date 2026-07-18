import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Store, Search, Plus, Eye, Tag,
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

interface Listing {
  id: string;
  seller_id: string;
  seller_username: string | null;
  name: string;
  tagline: string;
  description: string;
  category: string;
  tech_stack: string[];
  price: number;
  icon_url: string | null;
  screenshot_urls: string[];
  external_url: string | null;
  status: "draft" | "published" | "archived";
  view_count: number;
  created_at: string;
}

const CATEGORIES = [
  { value: "", label: "All Categories" },
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

export default function MarketplaceScreen() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<"browse" | "mine">("browse");
  const [listings, setListings] = useState<Listing[]>([]);
  const [myListings, setMyListings] = useState<Listing[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");

  useEffect(() => {
    if (tab === "browse") loadListings();
    else loadMyListings();
  }, [tab, category]);

  const loadListings = async () => {
    setIsLoading(true);
    try {
      const { data } = await apiClient.get("/marketplace/apps", {
        params: { search: search || undefined, category: category || undefined },
      });
      setListings(data.listings || []);
    } catch (error: any) {
      toast.error(error.message || "Failed to load marketplace listings.");
    } finally {
      setIsLoading(false);
    }
  };

  const loadMyListings = async () => {
    setIsLoading(true);
    try {
      const { data } = await apiClient.get("/marketplace/apps/mine");
      setMyListings(data.listings || []);
    } catch (error: any) {
      toast.error(error.message || "Failed to load your listings.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadListings();
  };

  const visibleListings = tab === "browse" ? listings : myListings;

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--color-background)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <BabyTiger size={36} expression="happy" />
        <div className="flex-1">
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">
            Marketplace
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Browse apps built by the community — buying is coming soon
          </p>
        </div>
        <button
          onClick={() => navigate("/marketplace/new")}
          className="px-4 py-2.5 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors flex items-center gap-2"
        >
          <Plus className="w-4 h-4" />
          New Listing
        </button>
      </div>

      {/* Tabs + filters */}
      <div className="px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <div className="flex items-center gap-2 mb-3">
          <button
            onClick={() => setTab("browse")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === "browse"
                ? "bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)]"
            }`}
          >
            Browse
          </button>
          <button
            onClick={() => setTab("mine")}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === "mine"
                ? "bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                : "text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)]"
            }`}
          >
            My Listings
          </button>
        </div>

        {tab === "browse" && (
          <div className="flex flex-col sm:flex-row gap-2">
            <form onSubmit={handleSearchSubmit} className="flex-1 relative">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)]" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search apps..."
                className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] pl-9 pr-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
              />
            </form>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
            >
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16">
            <BabyTiger size={80} expression="thinking" />
            <p className="text-sm text-[var(--color-text-secondary)]">Loading...</p>
          </div>
        ) : visibleListings.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
            <Store className="w-10 h-10 text-[var(--color-text-tertiary)]" />
            <p className="text-sm text-[var(--color-text-secondary)]">
              {tab === "browse"
                ? "No listings found yet."
                : "You haven't listed anything yet."}
            </p>
            {tab === "mine" && (
              <button
                onClick={() => navigate("/marketplace/new")}
                className="mt-2 px-4 py-2 rounded-lg bg-[var(--color-primary)] text-white text-sm font-semibold hover:bg-[var(--color-primary-hover)] transition-colors"
              >
                Create your first listing
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {visibleListings.map((listing, i) => (
              <motion.button
                key={listing.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i, 8) * 0.03 }}
                onClick={() => navigate(`/marketplace/apps/${listing.id}`)}
                className="text-left rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-4 hover:border-[var(--color-primary)] transition-colors"
              >
                <div className="flex items-start gap-3 mb-3">
                  {listing.icon_url ? (
                    <img
                      src={listing.icon_url}
                      alt={listing.name}
                      className="w-12 h-12 rounded-xl object-cover border border-[var(--color-border)] flex-shrink-0"
                    />
                  ) : (
                    <div className="w-12 h-12 rounded-xl bg-[var(--color-primary-light)] flex items-center justify-center flex-shrink-0">
                      <Store className="w-5 h-5 text-[var(--color-primary)]" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-[var(--color-text-primary)] truncate">
                      {listing.name}
                    </p>
                    <p className="text-xs text-[var(--color-text-tertiary)] truncate">
                      {listing.tagline}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap mb-3">
                  <span className="px-2 py-1 rounded-md bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)] text-xs border border-[var(--color-border)] flex items-center gap-1">
                    <Tag className="w-3 h-3" />
                    {listing.category.replace("_", " ")}
                  </span>
                  {tab === "mine" && (
                    <span
                      className={`px-2 py-1 rounded-md text-xs font-medium ${
                        listing.status === "published"
                          ? "bg-[var(--color-success-light)] text-[var(--color-success)]"
                          : "bg-[var(--color-warning-light)] text-[var(--color-warning)]"
                      }`}
                    >
                      {listing.status}
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between text-xs text-[var(--color-text-tertiary)]">
                  <span className="flex items-center gap-1">
                    <Eye className="w-3.5 h-3.5" />
                    {listing.view_count}
                  </span>
                  <span className="font-semibold text-[var(--color-text-primary)]">
                    {listing.price > 0 ? `₹${listing.price}` : "Free"}
                  </span>
                </div>
              </motion.button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
