import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowLeft, Store, Tag, Eye, ExternalLink, User as UserIcon,
  Trash2, Loader2,
} from "lucide-react";
import toast from "react-hot-toast";
import { useSelector } from "react-redux";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import { RootState } from "@/store";

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

export default function MarketplaceListingDetailScreen() {
  const { listingId } = useParams();
  const navigate = useNavigate();
  const { user } = useSelector((state: RootState) => state.auth);

  const [listing, setListing] = useState<Listing | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    loadListing();
  }, [listingId]);

  const loadListing = async () => {
    setIsLoading(true);
    try {
      const { data } = await apiClient.get(`/marketplace/apps/${listingId}`);
      setListing(data.listing);
    } catch (error: any) {
      toast.error(error.message || "Listing not found.");
      navigate("/marketplace");
    } finally {
      setIsLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!listing) return;
    setIsDeleting(true);
    try {
      await apiClient.delete(`/marketplace/apps/${listing.id}`);
      toast.success("Listing deleted");
      navigate("/marketplace");
    } catch (error: any) {
      toast.error(error.message || "Failed to delete listing.");
    } finally {
      setIsDeleting(false);
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

  if (!listing) return null;

  const isOwner = user?.id === listing.seller_id;

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
            {listing.name}
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">Marketplace Listing</p>
        </div>
        {isOwner && (
          <button
            onClick={handleDelete}
            disabled={isDeleting}
            className="px-3 py-2 rounded-lg border border-[var(--color-error)] text-[var(--color-error)] text-xs font-semibold hover:bg-[var(--color-error)] hover:text-white transition-colors disabled:opacity-60 flex items-center gap-1.5"
          >
            {isDeleting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Trash2 className="w-3.5 h-3.5" />
            )}
            Delete
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="max-w-2xl mx-auto space-y-6">
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6"
          >
            <div className="flex items-start gap-4 mb-4">
              {listing.icon_url ? (
                <img
                  src={listing.icon_url}
                  alt={listing.name}
                  className="w-16 h-16 rounded-2xl object-cover border border-[var(--color-border)] flex-shrink-0"
                />
              ) : (
                <div className="w-16 h-16 rounded-2xl bg-[var(--color-primary-light)] flex items-center justify-center flex-shrink-0">
                  <Store className="w-7 h-7 text-[var(--color-primary)]" />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <h2 className="text-xl font-bold text-[var(--color-text-primary)]">
                  {listing.name}
                </h2>
                <p className="text-sm text-[var(--color-text-secondary)]">{listing.tagline}</p>
                {listing.seller_username && (
                  <p className="text-xs text-[var(--color-text-tertiary)] mt-1 flex items-center gap-1">
                    <UserIcon className="w-3 h-3" />
                    by {listing.seller_username}
                  </p>
                )}
              </div>
              <div className="text-right flex-shrink-0">
                <p className="text-lg font-bold text-[var(--color-text-primary)]">
                  {listing.price > 0 ? `₹${listing.price}` : "Free"}
                </p>
                <p className="text-xs text-[var(--color-text-tertiary)] flex items-center gap-1 justify-end mt-1">
                  <Eye className="w-3 h-3" />
                  {listing.view_count} views
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap mb-4">
              <span className="px-2.5 py-1 rounded-md bg-[var(--color-surface-raised)] text-[var(--color-text-secondary)] text-xs border border-[var(--color-border)] flex items-center gap-1">
                <Tag className="w-3 h-3" />
                {listing.category.replace("_", " ")}
              </span>
              {listing.tech_stack.map((tech, i) => (
                <span
                  key={i}
                  className="px-2.5 py-1 rounded-md bg-[var(--color-primary-light)] text-[var(--color-primary)] text-xs font-medium"
                >
                  {tech}
                </span>
              ))}
            </div>

            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap">
              {listing.description}
            </p>

            {listing.external_url && (
              <a
                href={listing.external_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-5 w-full py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors flex items-center justify-center gap-2"
              >
                <ExternalLink className="w-4 h-4" />
                Visit App
              </a>
            )}
          </motion.div>

          {listing.screenshot_urls.length > 0 && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6"
            >
              <h3 className="text-sm font-semibold text-[var(--color-text-primary)] mb-3">
                Screenshots
              </h3>
              <div className="grid grid-cols-2 gap-3">
                {listing.screenshot_urls.map((url, i) => (
                  <img
                    key={i}
                    src={url}
                    alt={`Screenshot ${i + 1}`}
                    className="w-full rounded-xl border border-[var(--color-border)] object-cover"
                  />
                ))}
              </div>
            </motion.div>
          )}
        </div>
      </div>
    </div>
  );
}
