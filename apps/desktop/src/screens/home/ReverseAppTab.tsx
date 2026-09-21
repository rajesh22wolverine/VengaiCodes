import { useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Globe, Image as ImageIcon, FileText, Loader2, Sparkles, X, RotateCcw } from "lucide-react";
import toast from "react-hot-toast";

import { AppDispatch, RootState } from "@/store";
import { createProject } from "@/store/slices/projectSlice";
import { setTigerExpression } from "@/store/slices/uiSlice";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

type SourceType = "description" | "url" | "screenshots";

const SOURCE_TABS: { id: SourceType; label: string; icon: React.ElementType }[] = [
  { id: "description", label: "Describe it", icon: FileText },
  { id: "url", label: "Website URL", icon: Globe },
  { id: "screenshots", label: "Screenshots", icon: ImageIcon },
];

const MAX_SCREENSHOTS = 5;
const ALLOWED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];

interface Analysis {
  raw_idea: string;
  suggested_name: string;
}

export default function ReverseAppTab() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { isLoading: isCreating } = useSelector((state: RootState) => state.project);
  const { user } = useSelector((state: RootState) => state.auth);

  const [sourceType, setSourceType] = useState<SourceType>("description");
  const [description, setDescription] = useState("");
  const [url, setUrl] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);

  const canCreate = user ? user.projects_remaining > 0 : true;

  const handleFilesSelected = (selected: FileList | null) => {
    if (!selected) return;
    const next: File[] = [];
    for (const file of Array.from(selected)) {
      if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
        toast.error(`${file.name} isn't a supported image type (PNG, JPEG, or WebP).`);
        continue;
      }
      next.push(file);
    }
    setFiles((prev) => [...prev, ...next].slice(0, MAX_SCREENSHOTS));
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleAnalyze = async () => {
    if (sourceType === "description" && !description.trim()) {
      toast.error("Describe the app you want to clone first! 🐯");
      return;
    }
    if (sourceType === "url" && !url.trim()) {
      toast.error("Paste a website URL first! 🐯");
      return;
    }
    if (sourceType === "screenshots" && files.length === 0) {
      toast.error("Upload at least one screenshot first! 🐯");
      return;
    }

    setIsAnalyzing(true);
    dispatch(setTigerExpression("investigating"));

    try {
      const form = new FormData();
      form.append("source_type", sourceType);
      if (sourceType === "description") form.append("description", description.trim());
      if (sourceType === "url") form.append("url", url.trim());
      if (sourceType === "screenshots") files.forEach((f) => form.append("files", f));

      const { data } = await apiClient.post("/reverse/analyze", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120_000,
      });

      setAnalysis({ raw_idea: data.raw_idea, suggested_name: data.suggested_name });
      dispatch(setTigerExpression("excited"));
      toast.success("Got it! Review the idea below 🐯");
    } catch (error: any) {
      dispatch(setTigerExpression("sad"));
      toast.error(error.message || "Couldn't analyze that. Please try again!");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleBuild = async () => {
    if (!analysis) return;
    if (!canCreate) {
      toast.error("You've used all your free projects. Upgrade to create more! 🐯");
      return;
    }

    const result = await dispatch(
      createProject({ name: analysis.suggested_name, rawIdea: analysis.raw_idea })
    );

    if (createProject.fulfilled.match(result)) {
      dispatch(setTigerExpression("excited"));
      toast.success("Let's understand your idea! 🐯");
      navigate(`/project/${result.payload.id}/wizard`);
    }
  };

  const reset = () => {
    setAnalysis(null);
    setDescription("");
    setUrl("");
    setFiles([]);
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
            <BabyTiger size={100} expression={analysis ? "excited" : "investigating"} />
          </div>
          <h2 className="text-2xl font-bold text-[var(--color-text-primary)] mb-2">
            Rebuild an app you already love
          </h2>
          <p className="text-[var(--color-text-secondary)]">
            Point Baby Tiger at an existing app or website — a URL, screenshots, or just a
            description — and get a fresh, original app inspired by it, built your way.
          </p>
        </motion.div>

        <AnimatePresence mode="wait">
          {!analysis ? (
            <motion.div key="input" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              {/* Source type tabs */}
              <div className="flex gap-2 mb-4">
                {SOURCE_TABS.map((tab) => {
                  const Icon = tab.icon;
                  const isActive = sourceType === tab.id;
                  return (
                    <button
                      key={tab.id}
                      onClick={() => setSourceType(tab.id)}
                      className={`flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl border text-sm font-medium transition-colors ${
                        isActive
                          ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary)]"
                          : "border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]"
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                      {tab.label}
                    </button>
                  );
                })}
              </div>

              {/* Source input */}
              <div className="mb-4">
                {sourceType === "description" && (
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="e.g. Something like Notion, but focused just on meal planning and grocery lists..."
                    rows={5}
                    className="w-full px-4 py-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none transition-all resize-none text-sm leading-relaxed"
                  />
                )}

                {sourceType === "url" && (
                  <input
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://example.com"
                    className="w-full px-4 py-3 rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)] focus:ring-2 focus:ring-[var(--color-primary)] focus:border-[var(--color-primary)] outline-none transition-all text-sm"
                  />
                )}

                {sourceType === "screenshots" && (
                  <div>
                    <label className="flex flex-col items-center justify-center gap-2 px-4 py-8 rounded-2xl border-2 border-dashed border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-tertiary)] hover:border-[var(--color-primary)] hover:text-[var(--color-primary)] cursor-pointer transition-colors">
                      <ImageIcon className="w-6 h-6" />
                      <span className="text-sm font-medium">
                        Click to upload up to {MAX_SCREENSHOTS} screenshots
                      </span>
                      <span className="text-xs">PNG, JPEG, or WebP</span>
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        multiple
                        className="hidden"
                        onChange={(e) => handleFilesSelected(e.target.files)}
                      />
                    </label>

                    {files.length > 0 && (
                      <div className="flex flex-wrap gap-2 mt-3">
                        {files.map((file, i) => (
                          <div
                            key={`${file.name}-${i}`}
                            className="flex items-center gap-1.5 pl-3 pr-1.5 py-1.5 rounded-lg bg-[var(--color-surface-raised)] border border-[var(--color-border)] text-xs text-[var(--color-text-secondary)]"
                          >
                            <span className="max-w-[140px] truncate">{file.name}</span>
                            <button
                              onClick={() => removeFile(i)}
                              className="p-0.5 rounded hover:bg-[var(--color-border)] text-[var(--color-text-tertiary)]"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>

              <button
                onClick={handleAnalyze}
                disabled={isAnalyzing}
                className="w-full px-5 py-3 rounded-xl bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-white font-semibold text-sm transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-md hover:shadow-lg"
              >
                {isAnalyzing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Analyzing...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    Analyze &amp; Suggest an App
                  </>
                )}
              </button>
            </motion.div>
          ) : (
            <motion.div key="review" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 mb-4">
                <label className="block text-xs font-semibold text-[var(--color-text-tertiary)] uppercase tracking-wider mb-2">
                  App name
                </label>
                <input
                  value={analysis.suggested_name}
                  onChange={(e) => setAnalysis({ ...analysis, suggested_name: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-primary)] text-sm font-medium mb-4 outline-none focus:ring-2 focus:ring-[var(--color-primary)]"
                />

                <label className="block text-xs font-semibold text-[var(--color-text-tertiary)] uppercase tracking-wider mb-2">
                  Your app idea (edit as you like)
                </label>
                <textarea
                  value={analysis.raw_idea}
                  onChange={(e) => setAnalysis({ ...analysis, raw_idea: e.target.value })}
                  rows={7}
                  className="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-primary)] text-sm leading-relaxed outline-none focus:ring-2 focus:ring-[var(--color-primary)] resize-none"
                />
              </div>

              <div className="flex gap-2">
                <button
                  onClick={reset}
                  className="px-4 py-3 rounded-xl border border-[var(--color-border)] text-[var(--color-text-primary)] font-medium text-sm hover:bg-[var(--color-surface-raised)] transition-colors flex items-center gap-2"
                >
                  <RotateCcw className="w-4 h-4" />
                  Start over
                </button>
                <button
                  onClick={handleBuild}
                  disabled={isCreating || !analysis.raw_idea.trim()}
                  className="flex-1 px-5 py-3 rounded-xl bg-[var(--color-primary)] hover:bg-[var(--color-primary-hover)] text-white font-semibold text-sm transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-md hover:shadow-lg"
                >
                  {isCreating ? (
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
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
