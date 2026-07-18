import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Palette, Type, Layout, Puzzle,
  Navigation, Loader2, ThumbsUp, BookOpen, Upload,
  Wand2, Save, Trash2, ImageIcon, Code2
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";

interface ScreenDefinition {
  name: string;
  purpose: string;
  key_elements: string[];
}

interface ColorPalette {
  primary: string;
  secondary: string;
  accent: string;
  background: string;
  text: string;
}

interface UIUXDesign {
  design_style: string;
  color_palette: ColorPalette;
  typography: string;
  screens: ScreenDefinition[];
  components: string[];
  navigation_pattern: string;
}

interface UploadedDesign {
  id: string;
  page_name: string;
  image_url: string;
  uploaded_at: string;
  generated_html: string | null;
  generated_css: string | null;
  generation_notes: string | null;
  code_generated_at: string | null;
  code_updated_at: string | null;
}

export default function UIUXScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [design, setDesign] = useState<UIUXDesign | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  const [uploadedDesigns, setUploadedDesigns] = useState<UploadedDesign[]>([]);
  const [uploadPageName, setUploadPageName] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [generatingCodeFor, setGeneratingCodeFor] = useState<string | null>(null);
  const [expandedDesignId, setExpandedDesignId] = useState<string | null>(null);
  const [editedHtml, setEditedHtml] = useState("");
  const [editedCss, setEditedCss] = useState("");
  const [isSavingCode, setIsSavingCode] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/uiux/${projectId}`);
      setDesign(data.design);
      setUploadedDesigns(data.uploaded_designs || []);
      setIsLoading(false);
    } catch {
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/uiux/generate", {
        project_id: projectId,
      });
      setDesign(data.design);
      toast.success("Your design system is ready! 🎨🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to generate design.");
      navigate(`/project/${projectId}/requirements`);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownloadDocs = async () => {
    setIsDownloadingDocs(true);
    try {
      const response = await apiClient.get(`/export/${projectId}/documents`, {
        responseType: "blob",
      });
      const contentDisposition = response.headers["content-disposition"] || "";
      const filenameMatch = contentDisposition.match(/filename\s*=\s*"?([^";]+)"?/i);
      const downloadName = filenameMatch?.[1] || "documentation.zip";
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", downloadName);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      toast.success("Documentation bundle downloaded 🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to download documentation.");
    } finally {
      setIsDownloadingDocs(false);
    }
  };

  const handleApprove = async () => {
    setIsApproving(true);
    try {
      await apiClient.post("/uiux/approve", {
        project_id: projectId,
        approved: true,
      });
      toast.success("Design approved! Next: Architecture 🐯");
      navigate(`/project/${projectId}/architecture`);
    } catch (error: any) {
      toast.error(error.message || "Failed to approve.");
    } finally {
      setIsApproving(false);
    }
  };

  // ── Upload your own design → code ──

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const pageName = uploadPageName.trim() || file.name.replace(/\.[^.]+$/, "");
    const formData = new FormData();
    formData.append("page_name", pageName);
    formData.append("file", file);

    setIsUploading(true);
    try {
      const { data } = await apiClient.post(`/uiux/${projectId}/design/upload`, formData, {
        headers: { "Content-Type": undefined },
      });
      setUploadedDesigns((prev) => [...prev, data.design]);
      setUploadPageName("");
      toast.success("Design uploaded! 🖼️");
    } catch (error: any) {
      toast.error(error.message || "Failed to upload design.");
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleGenerateCode = async (designId: string) => {
    setGeneratingCodeFor(designId);
    try {
      const { data } = await apiClient.post(
        `/uiux/${projectId}/design/${designId}/generate-code`
      );
      setUploadedDesigns((prev) =>
        prev.map((d) => (d.id === designId ? data.design : d))
      );
      setEditedHtml(data.design.generated_html || "");
      setEditedCss(data.design.generated_css || "");
      setExpandedDesignId(designId);
      toast.success("Code generated from your design! 🐯✨");
    } catch (error: any) {
      toast.error(error.message || "Failed to generate code from design.");
    } finally {
      setGeneratingCodeFor(null);
    }
  };

  const handleExpandDesign = (design: UploadedDesign) => {
    if (expandedDesignId === design.id) {
      setExpandedDesignId(null);
      return;
    }
    setEditedHtml(design.generated_html || "");
    setEditedCss(design.generated_css || "");
    setExpandedDesignId(design.id);
  };

  const handleSaveCode = async (designId: string) => {
    setIsSavingCode(true);
    try {
      const { data } = await apiClient.put(`/uiux/${projectId}/design/${designId}/code`, {
        html: editedHtml,
        css: editedCss,
      });
      setUploadedDesigns((prev) =>
        prev.map((d) => (d.id === designId ? data.design : d))
      );
      toast.success("Changes saved 🐯");
    } catch (error: any) {
      toast.error(error.message || "Failed to save changes.");
    } finally {
      setIsSavingCode(false);
    }
  };

  const handleDeleteDesign = async (designId: string) => {
    try {
      await apiClient.delete(`/uiux/${projectId}/design/${designId}`);
      setUploadedDesigns((prev) => prev.filter((d) => d.id !== designId));
      if (expandedDesignId === designId) setExpandedDesignId(null);
      toast.success("Design removed");
    } catch (error: any) {
      toast.error(error.message || "Failed to delete design.");
    }
  };

  if (isLoading || isGenerating) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 bg-[var(--color-background)]">
        <BabyTiger size={100} expression="thinking" />
        <p className="text-[var(--color-text-secondary)] text-sm">
          {isGenerating
            ? "Baby Tiger is designing your app... 🎨🐯"
            : "Loading..."}
        </p>
      </div>
    );
  }

  if (!design) return null;

  const colorEntries = Object.entries(design.color_palette) as [keyof ColorPalette, string][];

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--color-background)] overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--color-border)] bg-[var(--color-surface)] flex-shrink-0">
        <button
          onClick={() => navigate("/home")}
          className="p-2 rounded-lg hover:bg-[var(--color-surface-raised)] transition-colors"
        >
          <ArrowLeft className="w-4 h-4 text-[var(--color-text-secondary)]" />
        </button>
        <BabyTiger size={36} expression="happy" />
        <div className="flex-1">
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">
            UI/UX Design
          </h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Phase 2 of 7 — Review and approve to continue
          </p>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-6">

          {/* Design Style */}
          <Section icon={Palette} title="Design Style">
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {design.design_style}
            </p>
          </Section>

          {/* Color Palette */}
          <Section icon={Palette} title="Color Palette">
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              {colorEntries.map(([key, hex]) => (
                <div key={key} className="flex flex-col items-center gap-2">
                  <div
                    className="w-full aspect-square rounded-xl border border-[var(--color-border)] shadow-sm"
                    style={{ backgroundColor: hex }}
                  />
                  <div className="text-center">
                    <p className="text-xs font-medium text-[var(--color-text-primary)] capitalize">
                      {key}
                    </p>
                    <p className="text-xs text-[var(--color-text-tertiary)] font-mono">
                      {hex}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          {/* Typography */}
          <Section icon={Type} title="Typography">
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {design.typography}
            </p>
          </Section>

          {/* Screens */}
          <Section icon={Layout} title={`Screens (${design.screens.length})`}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {design.screens.map((screen, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <div
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: design.color_palette.primary }}
                    />
                    <h4 className="text-sm font-semibold text-[var(--color-text-primary)]">
                      {screen.name}
                    </h4>
                  </div>
                  <p className="text-xs text-[var(--color-text-secondary)] mb-3 leading-relaxed">
                    {screen.purpose}
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {screen.key_elements.map((el, j) => (
                      <span
                        key={j}
                        className="px-2 py-1 rounded-md bg-[var(--color-surface)] text-[var(--color-text-tertiary)] text-xs border border-[var(--color-border)]"
                      >
                        {el}
                      </span>
                    ))}
                  </div>
                </motion.div>
              ))}
            </div>
          </Section>

          {/* Components */}
          <Section icon={Puzzle} title="Reusable Components">
            <div className="flex flex-wrap gap-2">
              {design.components.map((component, i) => (
                <span
                  key={i}
                  className="px-3 py-1.5 rounded-lg bg-[var(--color-primary-light)] text-[var(--color-primary)] text-xs font-medium capitalize"
                >
                  {component}
                </span>
              ))}
            </div>
          </Section>

          {/* Navigation Pattern */}
          <Section icon={Navigation} title="Navigation Pattern">
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed">
              {design.navigation_pattern}
            </p>
          </Section>

          {/* Upload your own design → code */}
          <Section icon={Upload} title="Upload Your Own Page Design">
            <p className="text-xs text-[var(--color-text-secondary)] mb-4 leading-relaxed">
              Have a mockup or screenshot for a page? Upload it and Baby Tiger will
              read the image and generate matching HTML/CSS you can edit before it
              feeds into code generation.
            </p>

            <div className="flex flex-col sm:flex-row gap-2 mb-4">
              <input
                value={uploadPageName}
                onChange={(e) => setUploadPageName(e.target.value)}
                placeholder="Page name (e.g. Login Screen)"
                className="flex-1 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
              />
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={handleFileSelected}
                className="hidden"
                id="design-upload-input"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="px-4 py-2.5 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center justify-center gap-2 whitespace-nowrap"
              >
                {isUploading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Upload className="w-4 h-4" />
                )}
                Upload Design
              </button>
            </div>

            {uploadedDesigns.length === 0 ? (
              <p className="text-xs text-[var(--color-text-tertiary)]">
                No designs uploaded yet.
              </p>
            ) : (
              <div className="space-y-3">
                {uploadedDesigns.map((d) => (
                  <div
                    key={d.id}
                    className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] overflow-hidden"
                  >
                    <div className="flex items-center gap-3 p-3">
                      <img
                        src={d.image_url}
                        alt={d.page_name}
                        className="w-14 h-14 rounded-lg object-cover border border-[var(--color-border)] flex-shrink-0"
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-[var(--color-text-primary)] truncate">
                          {d.page_name}
                        </p>
                        <p className="text-xs text-[var(--color-text-tertiary)]">
                          {d.generated_html ? "Code generated" : "Not converted yet"}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {d.generated_html ? (
                          <button
                            onClick={() => handleExpandDesign(d)}
                            className="px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-[var(--color-text-primary)] text-xs font-semibold hover:bg-[var(--color-surface)] transition-colors flex items-center gap-1.5"
                          >
                            <Code2 className="w-3.5 h-3.5" />
                            {expandedDesignId === d.id ? "Hide code" : "View/edit code"}
                          </button>
                        ) : (
                          <button
                            onClick={() => handleGenerateCode(d.id)}
                            disabled={generatingCodeFor === d.id}
                            className="px-3 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center gap-1.5"
                          >
                            {generatingCodeFor === d.id ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Wand2 className="w-3.5 h-3.5" />
                            )}
                            Generate Code
                          </button>
                        )}
                        <button
                          onClick={() => handleDeleteDesign(d.id)}
                          className="p-1.5 rounded-lg border border-[var(--color-border)] text-[var(--color-error)] hover:bg-[var(--color-surface)] transition-colors"
                          title="Delete design"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </div>

                    <AnimatePresence>
                      {expandedDesignId === d.id && (
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                          className="border-t border-[var(--color-border)] p-3"
                        >
                          {d.generation_notes && (
                            <p className="text-xs text-[var(--color-text-tertiary)] mb-3 italic flex items-start gap-1.5">
                              <ImageIcon className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                              {d.generation_notes}
                            </p>
                          )}
                          <div className="grid gap-3 sm:grid-cols-2">
                            <div>
                              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                                HTML
                              </label>
                              <textarea
                                value={editedHtml}
                                onChange={(e) => setEditedHtml(e.target.value)}
                                spellCheck={false}
                                className="w-full h-48 rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-xs font-mono text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)] resize-y"
                              />
                            </div>
                            <div>
                              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                                CSS
                              </label>
                              <textarea
                                value={editedCss}
                                onChange={(e) => setEditedCss(e.target.value)}
                                spellCheck={false}
                                className="w-full h-48 rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-xs font-mono text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)] resize-y"
                              />
                            </div>
                          </div>
                          <button
                            onClick={() => handleSaveCode(d.id)}
                            disabled={isSavingCode}
                            className="mt-3 px-4 py-2 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center gap-1.5"
                          >
                            {isSavingCode ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Save className="w-3.5 h-3.5" />
                            )}
                            Save Changes
                          </button>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                ))}
              </div>
            )}
          </Section>
        </div>
      </div>

      {/* Footer */}
      <div className="flex-shrink-0 px-6 py-4 border-t border-[var(--color-border)] bg-[var(--color-surface)]">
        <div className="max-w-3xl mx-auto flex items-center justify-between">
          <p className="text-xs text-[var(--color-text-tertiary)]">
            Review the design above. Once approved, Baby Tiger moves to Architecture 🏗️
          </p>
          <div className="flex items-center gap-3 flex-shrink-0">
            <button
              onClick={handleDownloadDocs}
              disabled={isDownloadingDocs}
              className="px-4 py-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-text-primary)] font-medium text-sm hover:bg-[var(--color-surface-raised)] transition-colors disabled:opacity-60 flex items-center gap-2"
            >
              {isDownloadingDocs ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <BookOpen className="w-4 h-4" />
              )}
              Export Docs
            </button>
            <button
              onClick={handleApprove}
              disabled={isApproving}
              className="px-6 py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center gap-2"
            >
              {isApproving ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <ThumbsUp className="w-4 h-4" />
              )}
              Approve & Continue
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  children,
}: {
  icon: React.ElementType;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5"
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon className="w-4 h-4 text-[var(--color-primary)]" />
        <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">
          {title}
        </h3>
      </div>
      {children}
    </motion.div>
  );
}
