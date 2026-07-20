import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft, Palette, Type, Layout, Puzzle,
  Navigation, Loader2, ThumbsUp, BookOpen, Upload,
  Wand2, Save, Trash2, ImageIcon, Code2, Camera, X,
  Mic, Square, FileAudio
} from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import ChatPanel from "@/components/chat/ChatPanel";
import { buildPreviewDocument, sendEditorCommand, type PreviewSelection } from "@/lib/designPreview";

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
  voice_note_url: string | null;
  voice_note_transcript: string | null;
  voice_note_uploaded_at: string | null;
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

  const [previewDoc, setPreviewDoc] = useState("");
  const [selection, setSelection] = useState<PreviewSelection | null>(null);
  const previewFrameRef = useRef<HTMLIFrameElement>(null);
  const skipNextRebuildRef = useRef(false);

  const [isCameraOpen, setIsCameraOpen] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);

  const [recordingDesignId, setRecordingDesignId] = useState<string | null>(null);
  const [transcribingDesignId, setTranscribingDesignId] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  useEffect(() => {
    return () => {
      cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
      mediaRecorderRef.current?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  // Live preview: rebuild the iframe doc a beat after HTML/CSS changes so
  // typing in the code editors is reflected without reloading on every
  // keystroke. Visual edits made inside the iframe itself update
  // editedHtml via the "content-changed" message below — skip the next
  // rebuild in that case so we don't reload the frame the user is
  // actively editing in.
  useEffect(() => {
    if (!expandedDesignId) return;
    if (skipNextRebuildRef.current) {
      skipNextRebuildRef.current = false;
      return;
    }
    const t = setTimeout(() => {
      setPreviewDoc(buildPreviewDocument(editedHtml, editedCss));
    }, 350);
    return () => clearTimeout(t);
  }, [editedHtml, editedCss, expandedDesignId]);

  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (!previewFrameRef.current || e.source !== previewFrameRef.current.contentWindow) return;
      let data: any;
      try {
        data = typeof e.data === "string" ? JSON.parse(e.data) : e.data;
      } catch {
        return;
      }
      if (data?.source !== "vengaicode-preview") return;

      if (data.type === "ready" || data.type === "deselect") {
        setSelection(null);
      } else if (data.type === "select") {
        setSelection(data as PreviewSelection);
      } else if (data.type === "content-changed") {
        skipNextRebuildRef.current = true;
        setEditedHtml(data.html);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const updateStyle = (prop: string, value: string) => {
    if (!selection) return;
    sendEditorCommand(previewFrameRef.current?.contentWindow, { type: "set-style", prop, value });
    setSelection((s) => (s ? { ...s, styles: { ...s.styles, [prop]: value } } : s));
  };

  const updatePlaceholder = (value: string) => {
    if (!selection) return;
    sendEditorCommand(previewFrameRef.current?.contentWindow, { type: "set-placeholder", value });
    setSelection((s) => (s ? { ...s, placeholder: value } : s));
  };

  const clearPreviewSelection = () => {
    sendEditorCommand(previewFrameRef.current?.contentWindow, { type: "deselect" });
    setSelection(null);
  };

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

  const uploadDesignFile = async (file: File, fallbackName: string) => {
    const pageName = uploadPageName.trim() || fallbackName;
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
    }
  };

  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadDesignFile(file, file.name.replace(/\.[^.]+$/, ""));
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  // ── Camera capture (sketch/whiteboard/physical mockup photo) ──

  const openCamera = async () => {
    setCameraError(null);
    setIsCameraOpen(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      cameraStreamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
    } catch (error: any) {
      setCameraError(
        "Couldn't access your camera. Check camera permissions and try again."
      );
    }
  };

  const closeCamera = () => {
    cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
    cameraStreamRef.current = null;
    setIsCameraOpen(false);
  };

  const capturePhoto = async () => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    canvas.toBlob(async (blob) => {
      if (!blob) return;
      closeCamera();
      const file = new File([blob], `camera-capture-${Date.now()}.png`, { type: "image/png" });
      await uploadDesignFile(file, "Camera Capture");
    }, "image/png");
  };

  // ── Voice note (record + transcribe) ──

  const startRecording = async (designId: string) => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecordingDesignId(designId);
    } catch (error: any) {
      toast.error("Couldn't access your microphone. Check permissions and try again.");
    }
  };

  const stopRecording = async (designId: string) => {
    const recorder = mediaRecorderRef.current;
    if (!recorder) return;

    const stopped = new Promise<Blob>((resolve) => {
      recorder.onstop = () => {
        recorder.stream.getTracks().forEach((track) => track.stop());
        resolve(new Blob(audioChunksRef.current, { type: recorder.mimeType || "audio/webm" }));
      };
    });
    recorder.stop();
    setRecordingDesignId(null);

    const audioBlob = await stopped;
    if (audioBlob.size === 0) return;

    setTranscribingDesignId(designId);
    try {
      const formData = new FormData();
      const ext = audioBlob.type.includes("ogg") ? "ogg" : "webm";
      formData.append("file", new File([audioBlob], `voice-note.${ext}`, { type: audioBlob.type }));

      const { data } = await apiClient.post(
        `/uiux/${projectId}/design/${designId}/voice-note`,
        formData,
        { headers: { "Content-Type": undefined } }
      );
      setUploadedDesigns((prev) => prev.map((d) => (d.id === designId ? data.design : d)));
      if (data.transcription_failed) {
        toast.error("Voice note saved, but transcription failed. You can try recording again.");
      } else {
        toast.success("Voice note transcribed! 🎙️");
      }
    } catch (error: any) {
      toast.error(error.message || "Failed to save voice note.");
    } finally {
      setTranscribingDesignId(null);
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
      setSelection(null);
      setPreviewDoc(buildPreviewDocument(data.design.generated_html || "", data.design.generated_css || ""));
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
      setSelection(null);
      return;
    }
    setEditedHtml(design.generated_html || "");
    setEditedCss(design.generated_css || "");
    setSelection(null);
    setPreviewDoc(buildPreviewDocument(design.generated_html || "", design.generated_css || ""));
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
              <button
                onClick={openCamera}
                disabled={isUploading}
                className="px-4 py-2.5 rounded-xl border border-[var(--color-primary)] text-[var(--color-primary)] font-semibold text-sm hover:bg-[var(--color-primary-light)] transition-colors disabled:opacity-60 flex items-center justify-center gap-2 whitespace-nowrap"
              >
                <Camera className="w-4 h-4" />
                Use Camera
              </button>
            </div>

            <AnimatePresence>
              {isCameraOpen && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6"
                >
                  <div className="bg-[var(--color-surface)] rounded-2xl p-4 max-w-lg w-full">
                    <div className="flex items-center justify-between mb-3">
                      <p className="text-sm font-semibold text-[var(--color-text-primary)]">
                        Capture your design
                      </p>
                      <button
                        onClick={closeCamera}
                        className="p-1.5 rounded-lg hover:bg-[var(--color-surface-raised)] transition-colors"
                      >
                        <X className="w-4 h-4 text-[var(--color-text-secondary)]" />
                      </button>
                    </div>

                    {cameraError ? (
                      <p className="text-sm text-[var(--color-error)] py-8 text-center">
                        {cameraError}
                      </p>
                    ) : (
                      <>
                        <video
                          ref={videoRef}
                          autoPlay
                          playsInline
                          muted
                          className="w-full rounded-xl bg-black aspect-video object-cover"
                        />
                        <canvas ref={canvasRef} className="hidden" />
                        <button
                          onClick={capturePhoto}
                          className="mt-3 w-full py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors flex items-center justify-center gap-2"
                        >
                          <Camera className="w-4 h-4" />
                          Capture Photo
                        </button>
                      </>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

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
                        {d.voice_note_url && (
                          <p className="text-xs text-[var(--color-primary)] flex items-center gap-1 mt-0.5">
                            <FileAudio className="w-3 h-3" />
                            {d.voice_note_transcript
                              ? "Voice note attached"
                              : "Voice note attached (transcription failed)"}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {recordingDesignId === d.id ? (
                          <button
                            onClick={() => stopRecording(d.id)}
                            className="px-3 py-1.5 rounded-lg bg-[var(--color-error)] text-white text-xs font-semibold flex items-center gap-1.5 animate-pulse"
                          >
                            <Square className="w-3.5 h-3.5" />
                            Stop
                          </button>
                        ) : (
                          <button
                            onClick={() => startRecording(d.id)}
                            disabled={transcribingDesignId === d.id || recordingDesignId !== null}
                            title="Record a voice note with extra instructions"
                            className="p-2 rounded-lg border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-surface)] transition-colors disabled:opacity-60"
                          >
                            {transcribingDesignId === d.id ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Mic className="w-3.5 h-3.5" />
                            )}
                          </button>
                        )}
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
                          {d.voice_note_url && (
                            <div className="mb-3 p-2.5 rounded-lg bg-[var(--color-background)] border border-[var(--color-border)]">
                              <p className="text-xs font-medium text-[var(--color-text-secondary)] mb-1.5 flex items-center gap-1.5">
                                <FileAudio className="w-3.5 h-3.5" />
                                Voice note
                              </p>
                              <audio src={d.voice_note_url} controls className="w-full h-8 mb-1.5" />
                              {d.voice_note_transcript && (
                                <p className="text-xs text-[var(--color-text-tertiary)] italic">
                                  "{d.voice_note_transcript}"
                                </p>
                              )}
                            </div>
                          )}
                          <div className="grid gap-3 lg:grid-cols-2">
                            <div className="space-y-3">
                              <div>
                                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                                  HTML
                                </label>
                                <textarea
                                  value={editedHtml}
                                  onChange={(e) => setEditedHtml(e.target.value)}
                                  spellCheck={false}
                                  className="w-full h-40 rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-xs font-mono text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)] resize-y"
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
                                  className="w-full h-40 rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-xs font-mono text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)] resize-y"
                                />
                              </div>
                            </div>

                            <div>
                              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                                Live Preview — click any element to edit it directly
                              </label>
                              <div className="relative rounded-lg border border-[var(--color-border)] overflow-hidden" style={{ height: 336 }}>
                                <iframe
                                  ref={previewFrameRef}
                                  srcDoc={previewDoc}
                                  sandbox="allow-scripts"
                                  title="Design preview"
                                  className="w-full h-full bg-white"
                                />

                                {selection && (
                                  <div className="absolute top-2 right-2 w-52 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3 shadow-lg space-y-2.5 text-xs">
                                    <div className="flex items-center justify-between">
                                      <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-[var(--color-surface-raised)] text-[var(--color-text-tertiary)]">
                                        {selection.tag}
                                      </span>
                                      <button
                                        onClick={clearPreviewSelection}
                                        className="p-0.5 rounded hover:bg-[var(--color-surface-raised)]"
                                        title="Deselect"
                                      >
                                        <X className="w-3.5 h-3.5 text-[var(--color-text-tertiary)]" />
                                      </button>
                                    </div>

                                    {selection.isField ? (
                                      <div>
                                        <label className="block text-[10px] text-[var(--color-text-tertiary)] mb-1">Placeholder</label>
                                        <input
                                          value={selection.placeholder ?? ""}
                                          onChange={(e) => updatePlaceholder(e.target.value)}
                                          className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-background)] px-2 py-1 text-xs text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                                        />
                                      </div>
                                    ) : (
                                      <p className="text-[10px] text-[var(--color-text-tertiary)] italic">
                                        Click the text in the preview to edit it directly.
                                      </p>
                                    )}

                                    <div className="flex items-center gap-2">
                                      <div className="flex-1">
                                        <label className="block text-[10px] text-[var(--color-text-tertiary)] mb-1">Text</label>
                                        <input
                                          type="color"
                                          value={selection.styles.color || "#000000"}
                                          onChange={(e) => updateStyle("color", e.target.value)}
                                          className="w-full h-7 rounded-md border border-[var(--color-border)] cursor-pointer"
                                        />
                                      </div>
                                      <div className="flex-1">
                                        <label className="block text-[10px] text-[var(--color-text-tertiary)] mb-1">Background</label>
                                        <input
                                          type="color"
                                          value={selection.styles.backgroundColor || "#ffffff"}
                                          onChange={(e) => updateStyle("backgroundColor", e.target.value)}
                                          className="w-full h-7 rounded-md border border-[var(--color-border)] cursor-pointer"
                                        />
                                      </div>
                                    </div>

                                    <div>
                                      <label className="block text-[10px] text-[var(--color-text-tertiary)] mb-1">Font size</label>
                                      <input
                                        type="number"
                                        min={8}
                                        max={96}
                                        value={selection.styles.fontSize}
                                        onChange={(e) => updateStyle("fontSize", `${e.target.value}px`)}
                                        className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-background)] px-2 py-1 text-xs text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
                                      />
                                    </div>

                                    <div className="flex items-center gap-1.5">
                                      <button
                                        onClick={() =>
                                          updateStyle(
                                            "fontWeight",
                                            selection.styles.fontWeight === "bold" || parseInt(selection.styles.fontWeight) >= 700
                                              ? "400"
                                              : "700"
                                          )
                                        }
                                        className={`flex-1 py-1.5 rounded-md border text-xs font-bold ${
                                          selection.styles.fontWeight === "bold" || parseInt(selection.styles.fontWeight) >= 700
                                            ? "border-[var(--color-primary)] text-[var(--color-primary)] bg-[var(--color-primary-light)]"
                                            : "border-[var(--color-border)] text-[var(--color-text-secondary)]"
                                        }`}
                                      >
                                        B
                                      </button>
                                      {(["left", "center", "right"] as const).map((align) => (
                                        <button
                                          key={align}
                                          onClick={() => updateStyle("textAlign", align)}
                                          className={`flex-1 py-1.5 rounded-md border text-[10px] capitalize ${
                                            selection.styles.textAlign === align
                                              ? "border-[var(--color-primary)] text-[var(--color-primary)] bg-[var(--color-primary-light)]"
                                              : "border-[var(--color-border)] text-[var(--color-text-secondary)]"
                                          }`}
                                        >
                                          {align}
                                        </button>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </div>
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
      <ChatPanel projectId={projectId} phase="uiux" />
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
