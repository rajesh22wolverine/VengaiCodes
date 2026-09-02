import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Image, Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { RecordingPresets, requestRecordingPermissionsAsync, setAudioModeAsync, useAudioRecorder } from "expo-audio";
import { WebView, type WebViewMessageEvent } from "react-native-webview";
import DraggableFlatList, { type RenderItemParams, ScaleDecorator } from "react-native-draggable-flatlist";
import {
  BookOpen, Camera, Code2, Eye, FileAudio, Frame, GripVertical, ImageIcon, Layout, LayoutTemplate, Mic,
  Navigation, Palette, Puzzle, Save, Square, ThumbsUp, Trash2, Type, Upload, Wand2, X,
} from "lucide-react-native";

import apiClient from "@/lib/api";
import { downloadAndShareFile } from "@/lib/download";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";
import PhaseHeader from "@/components/phase/PhaseHeader";
import PhaseLoading from "@/components/phase/PhaseLoading";
import PhaseFooter from "@/components/phase/PhaseFooter";
import Section from "@/components/ui/Section";
import TextField from "@/components/ui/TextField";
import { buildPreviewDocument, type PreviewSelection } from "@/lib/designPreview";
import DesignStudioModal from "@/components/design-studio/DesignStudioModal";

interface ScreenDefinition {
  id: string;
  name: string;
  purpose: string;
  key_elements: string[];
  generated_html: string | null;
  generated_css: string | null;
  modules?: string[];
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
  page_order?: string[];
}

interface UploadedDesign {
  id: string;
  page_name: string;
  image_url: string;
  uploaded_at: string;
  generated_html: string | null;
  generated_css: string | null;
  generation_notes: string | null;
  modules?: string[];
  code_generated_at: string | null;
  code_updated_at: string | null;
  voice_note_url: string | null;
  voice_note_transcript: string | null;
  voice_note_uploaded_at: string | null;
}

// Unified shape both wizard-generated screens and user-uploaded mockups get
// rendered/reordered/edited as — combining them into one list is what makes
// a single drag-and-drop order and a single visual editor possible.
interface Page {
  id: string;
  kind: "screen" | "upload";
  name: string;
  purpose?: string;
  key_elements?: string[];
  image_url?: string;
  generated_html: string | null;
  generated_css: string | null;
  modules?: string[];
  generation_notes?: string | null;
  voice_note_url?: string | null;
  voice_note_transcript?: string | null;
}

// Saved page_order only ever lists ids that existed when it was written —
// merge it with whatever ids actually exist now so a freshly uploaded (or
// not-yet-ordered) page still shows up, appended at the end. Mirrors the
// backend's get_ordered_pages() fallback shape.
function computePageOrder(design: UIUXDesign, uploads: UploadedDesign[]): string[] {
  const allIds = [...design.screens.map((s) => s.id), ...uploads.map((d) => d.id)];
  const saved = design.page_order || [];
  const known = saved.filter((id) => allIds.includes(id));
  const missing = allIds.filter((id) => !known.includes(id));
  return [...known, ...missing];
}

function guessImageMimeType(asset: ImagePicker.ImagePickerAsset): string {
  if (asset.mimeType) return asset.mimeType;
  const ext = asset.uri.split(".").pop()?.toLowerCase();
  if (ext === "png") return "image/png";
  if (ext === "webp") return "image/webp";
  return "image/jpeg";
}

const MAX_VISIBLE_MODULE_TAGS = 5;

function ModuleTags({ modules }: { modules: string[] | undefined }) {
  const { colors } = useTheme();
  const clean = (modules ?? []).filter((m): m is string => typeof m === "string");
  if (clean.length === 0) return null;
  const visible = clean.slice(0, MAX_VISIBLE_MODULE_TAGS);
  const hiddenCount = clean.length - visible.length;
  return (
    <View style={styles.pillRow}>
      {visible.map((m, i) => (
        <View key={i} style={[styles.elementPill, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{m}</Text>
        </View>
      ))}
      {hiddenCount > 0 && (
        <View style={[styles.elementPill, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Text style={{ color: colors.textTertiary, fontSize: 11 }}>+{hiddenCount} more</Text>
        </View>
      )}
    </View>
  );
}

export default function UIUXScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const { showToast } = useToast();

  const [design, setDesign] = useState<UIUXDesign | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isDownloadingDocs, setIsDownloadingDocs] = useState(false);

  const [uploadedDesigns, setUploadedDesigns] = useState<UploadedDesign[]>([]);
  const [uploadPageName, setUploadPageName] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [generatingCodeFor, setGeneratingCodeFor] = useState<string | null>(null);
  const [expandedPageId, setExpandedPageId] = useState<string | null>(null);
  const [editedHtml, setEditedHtml] = useState("");
  const [editedCss, setEditedCss] = useState("");

  // Authoritative page order (wizard screens + uploads, mixed together).
  // Drag-and-drop only ever updates this — nothing is persisted until Save.
  const [pageOrder, setPageOrder] = useState<string[]>([]);
  const [isSavingPages, setIsSavingPages] = useState(false);

  const [isFigmaModalOpen, setIsFigmaModalOpen] = useState(false);
  const [figmaUrl, setFigmaUrl] = useState("");
  const [isImportingFigma, setIsImportingFigma] = useState(false);

  const [recordingDesignId, setRecordingDesignId] = useState<string | null>(null);
  const [transcribingDesignId, setTranscribingDesignId] = useState<string | null>(null);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recordingDesignIdRef = useRef<string | null>(null);

  const [designStudioPageId, setDesignStudioPageId] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<"code" | "preview">("preview");
  const [previewDoc, setPreviewDoc] = useState("");
  const [selection, setSelection] = useState<PreviewSelection | null>(null);
  const webViewRef = useRef<WebView>(null);
  const skipNextRebuildRef = useRef(false);

  useEffect(() => {
    loadOrGenerate();
  }, [projectId]);

  const loadOrGenerate = async () => {
    try {
      const { data } = await apiClient.get(`/uiux/${projectId}`);
      const uploads: UploadedDesign[] = data.uploaded_designs || [];
      setDesign(data.design);
      setUploadedDesigns(uploads);
      setPageOrder(computePageOrder(data.design, uploads));
      setIsLoading(false);
    } catch {
      await generate();
    }
  };

  const generate = async () => {
    setIsGenerating(true);
    setIsLoading(false);
    try {
      const { data } = await apiClient.post("/uiux/generate", { project_id: projectId });
      setDesign(data.design);
      setPageOrder(computePageOrder(data.design, []));
      showToast("Your design system is ready! 🎨🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to generate design.", "error");
      router.replace(`/(app)/project/${projectId}/requirements` as any);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleDownloadDocs = async () => {
    setIsDownloadingDocs(true);
    try {
      await downloadAndShareFile(`/export/${projectId}/documents`, "documentation.zip");
      showToast("Documentation bundle downloaded 🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to download documentation.", "error");
    } finally {
      setIsDownloadingDocs(false);
    }
  };

  const handleApprove = async () => {
    setIsApproving(true);
    try {
      await apiClient.post("/uiux/approve", { project_id: projectId, approved: true });
      showToast("Design approved! Next: pick your tech stack 🐯");
      router.replace(`/(app)/project/${projectId}/stack` as any);
    } catch (error: any) {
      showToast(error.message || "Failed to approve.", "error");
    } finally {
      setIsApproving(false);
    }
  };

  // Live preview: rebuild the WebView doc a beat after HTML/CSS changes so
  // typing in the code editor is reflected without reloading on every
  // keystroke. Visual edits made inside the WebView itself update
  // editedHtml via the "content-changed" message below — skip the next
  // rebuild in that case so we don't reload the page the user is
  // actively editing in.
  useEffect(() => {
    if (!expandedPageId) return;
    if (skipNextRebuildRef.current) {
      skipNextRebuildRef.current = false;
      return;
    }
    const t = setTimeout(() => {
      setPreviewDoc(buildPreviewDocument(editedHtml, editedCss));
    }, 350);
    return () => clearTimeout(t);
  }, [editedHtml, editedCss, expandedPageId]);

  // Shared by every page-editing path (raw code editor, click-to-edit
  // preview, and Design Studio) so there's one place that knows how to
  // patch either a wizard-generated screen or an uploaded/imported design
  // by id.
  const applyPageEdit = useCallback((pageId: string, html: string, css: string) => {
    setDesign((prev) => {
      if (!prev) return prev;
      const idx = prev.screens.findIndex((s) => s.id === pageId);
      const current = idx === -1 ? undefined : prev.screens[idx];
      if (!current) return prev;
      if (current.generated_html === html && current.generated_css === css) return prev;
      const screens = [...prev.screens];
      screens[idx] = { ...current, generated_html: html, generated_css: css };
      return { ...prev, screens };
    });
    setUploadedDesigns((prev) => {
      const idx = prev.findIndex((d) => d.id === pageId);
      const current = idx === -1 ? undefined : prev[idx];
      if (!current) return prev;
      if (current.generated_html === html && current.generated_css === css) return prev;
      const next = [...prev];
      next[idx] = { ...current, generated_html: html, generated_css: css };
      return next;
    });
  }, []);

  // Keep whichever page is currently expanded in sync with its live-edited
  // HTML/CSS, so switching to another page (or hitting the global Save
  // button) never loses in-progress edits — there's no more per-page save.
  useEffect(() => {
    if (!expandedPageId) return;
    applyPageEdit(expandedPageId, editedHtml, editedCss);
  }, [editedHtml, editedCss, expandedPageId, applyPageEdit]);

  const handlePreviewMessage = (event: WebViewMessageEvent) => {
    let data: any;
    try {
      data = JSON.parse(event.nativeEvent.data);
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

  const sendEditorCommand = (command: Record<string, unknown>) => {
    webViewRef.current?.postMessage(JSON.stringify({ source: "vengaicode-editor", ...command }));
  };

  const updateStyle = (prop: string, value: string) => {
    if (!selection) return;
    sendEditorCommand({ type: "set-style", prop, value });
    setSelection((s) => (s ? { ...s, styles: { ...s.styles, [prop]: value } } : s));
  };

  const updatePlaceholder = (value: string) => {
    if (!selection) return;
    sendEditorCommand({ type: "set-placeholder", value });
    setSelection((s) => (s ? { ...s, placeholder: value } : s));
  };

  const clearPreviewSelection = () => {
    sendEditorCommand({ type: "deselect" });
    setSelection(null);
  };

  const moveElement = (direction: "up" | "down") => {
    sendEditorCommand({ type: "move-element", direction });
  };

  const moveModule = (direction: "up" | "down") => {
    sendEditorCommand({ type: "move-module", direction });
  };

  // ── Save every pending edit + the current page order in one action ──

  const pagesById = useMemo(() => {
    const map = new Map<string, Page>();
    (design?.screens || []).forEach((s) => {
      map.set(s.id, {
        id: s.id,
        kind: "screen",
        name: s.name,
        purpose: s.purpose,
        key_elements: s.key_elements,
        generated_html: s.generated_html,
        generated_css: s.generated_css,
        modules: s.modules,
      });
    });
    uploadedDesigns.forEach((d) => {
      map.set(d.id, {
        id: d.id,
        kind: "upload",
        name: d.page_name,
        image_url: d.image_url,
        generated_html: d.generated_html,
        generated_css: d.generated_css,
        modules: d.modules,
        generation_notes: d.generation_notes,
        voice_note_url: d.voice_note_url,
        voice_note_transcript: d.voice_note_transcript,
      });
    });
    return map;
  }, [design, uploadedDesigns]);

  const pages: Page[] = pageOrder.map((id) => pagesById.get(id)).filter((p): p is Page => !!p);

  const handleSaveAll = async () => {
    if (!design) return;
    setIsSavingPages(true);
    try {
      const payloadPages = pages.map((p) => ({
        id: p.id,
        generated_html: p.generated_html,
        generated_css: p.generated_css,
        modules: p.modules || [],
      }));
      await apiClient.put(`/uiux/${projectId}/save`, {
        project_id: projectId,
        pages: payloadPages,
        page_order: pageOrder,
      });
      showToast("Design saved 🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to save design.", "error");
    } finally {
      setIsSavingPages(false);
    }
  };

  // ── Upload your own design → code ──

  const uploadDesignAsset = async (asset: ImagePicker.ImagePickerAsset, fallbackName: string) => {
    const pageName = uploadPageName.trim() || fallbackName;
    const formData = new FormData();
    formData.append("page_name", pageName);
    formData.append(
      "file",
      {
        uri: asset.uri,
        name: asset.fileName || `design-${Date.now()}.jpg`,
        type: guessImageMimeType(asset),
      } as any
    );

    setIsUploading(true);
    try {
      const { data } = await apiClient.post(`/uiux/${projectId}/design/upload`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadedDesigns((prev) => [...prev, data.design]);
      setPageOrder((prev) => [...prev, data.design.id]);
      setUploadPageName("");
      showToast("Design uploaded! 🖼️");
    } catch (error: any) {
      showToast(error.message || "Failed to upload design.", "error");
    } finally {
      setIsUploading(false);
    }
  };

  const pickFromLibrary = async () => {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      showToast("Photo library access is needed to upload a design.", "error");
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.9 });
    if (result.canceled || !result.assets[0]) return;
    await uploadDesignAsset(result.assets[0], "Uploaded Design");
  };

  const captureFromCamera = async () => {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      showToast("Camera access is needed to capture a design.", "error");
      return;
    }
    const result = await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 0.9 });
    if (result.canceled || !result.assets[0]) return;
    await uploadDesignAsset(result.assets[0], "Camera Capture");
  };

  // ── Import from Figma ──

  const importFromFigma = async () => {
    if (!figmaUrl.trim()) {
      showToast("Paste a Figma frame link first.", "error");
      return;
    }
    const pageName = uploadPageName.trim() || "Figma Import";
    setIsImportingFigma(true);
    try {
      const { data } = await apiClient.post(`/uiux/${projectId}/design/import-figma`, {
        figma_url: figmaUrl.trim(),
        page_name: pageName,
      });
      setUploadedDesigns((prev) => [...prev, data.design]);
      setPageOrder((prev) => [...prev, data.design.id]);
      setUploadPageName("");
      setFigmaUrl("");
      setIsFigmaModalOpen(false);
      showToast("Imported from Figma! 🎨🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to import from Figma.", "error");
    } finally {
      setIsImportingFigma(false);
    }
  };

  // ── Voice note (record + transcribe) ──

  const startRecording = async (designId: string) => {
    try {
      const permission = await requestRecordingPermissionsAsync();
      if (!permission.granted) {
        showToast("Microphone access is needed to record a voice note.", "error");
        return;
      }
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      recordingDesignIdRef.current = designId;
      setRecordingDesignId(designId);
    } catch {
      showToast("Couldn't start recording. Please try again.", "error");
    }
  };

  const stopRecording = async () => {
    const designId = recordingDesignIdRef.current;
    if (!designId) return;

    setRecordingDesignId(null);
    recordingDesignIdRef.current = null;
    try {
      await recorder.stop();
    } catch {
      // fall through — still try whatever uri is available
    }

    const uri = recorder.uri;
    if (!uri) {
      showToast("Recording was too short to save.", "error");
      return;
    }

    setTranscribingDesignId(designId);
    try {
      const formData = new FormData();
      formData.append(
        "file",
        { uri, name: `voice-note-${Date.now()}.m4a`, type: "audio/x-m4a" } as any
      );

      const { data } = await apiClient.post(
        `/uiux/${projectId}/design/${designId}/voice-note`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      setUploadedDesigns((prev) => prev.map((d) => (d.id === designId ? data.design : d)));
      if (data.transcription_failed) {
        showToast("Voice note saved, but transcription failed. You can try recording again.", "error");
      } else {
        showToast("Voice note transcribed! 🎙️");
      }
    } catch (error: any) {
      showToast(error.message || "Failed to save voice note.", "error");
    } finally {
      setTranscribingDesignId(null);
    }
  };

  const handleGenerateCode = async (designId: string) => {
    setGeneratingCodeFor(designId);
    try {
      const { data } = await apiClient.post(`/uiux/${projectId}/design/${designId}/generate-code`);
      setUploadedDesigns((prev) => prev.map((d) => (d.id === designId ? data.design : d)));
      setEditedHtml(data.design.generated_html || "");
      setEditedCss(data.design.generated_css || "");
      setSelection(null);
      setPreviewDoc(buildPreviewDocument(data.design.generated_html || "", data.design.generated_css || ""));
      setActiveTab("preview");
      setExpandedPageId(designId);
      showToast("Code generated from your design! 🐯✨");
    } catch (error: any) {
      showToast(error.message || "Failed to generate code from design.", "error");
    } finally {
      setGeneratingCodeFor(null);
    }
  };

  const handleExpandPage = (page: Page) => {
    if (expandedPageId === page.id) {
      setExpandedPageId(null);
      setSelection(null);
      return;
    }
    setEditedHtml(page.generated_html || "");
    setEditedCss(page.generated_css || "");
    setSelection(null);
    setPreviewDoc(buildPreviewDocument(page.generated_html || "", page.generated_css || ""));
    setActiveTab("preview");
    setExpandedPageId(page.id);
  };

  const handleDeleteDesign = async (designId: string) => {
    try {
      await apiClient.delete(`/uiux/${projectId}/design/${designId}`);
      setUploadedDesigns((prev) => prev.filter((d) => d.id !== designId));
      setPageOrder((prev) => prev.filter((id) => id !== designId));
      if (expandedPageId === designId) setExpandedPageId(null);
      showToast("Design removed");
    } catch (error: any) {
      showToast(error.message || "Failed to delete design.", "error");
    }
  };

  if (isLoading || isGenerating) {
    return <PhaseLoading message={isGenerating ? "Baby Tiger is designing your app... 🎨🐯" : "Loading..."} />;
  }

  if (!design) return null;

  const colorEntries = Object.entries(design.color_palette) as [keyof ColorPalette, string][];

  const renderPageItem = ({ item, drag, isActive }: RenderItemParams<Page>) => (
    <ScaleDecorator>
      <PageCard
        page={item}
        drag={drag}
        isActive={isActive}
        isExpanded={expandedPageId === item.id}
        onToggleExpand={handleExpandPage}
        onGenerateCode={handleGenerateCode}
        generatingCode={generatingCodeFor === item.id}
        onDelete={handleDeleteDesign}
        recording={recordingDesignId === item.id}
        transcribing={transcribingDesignId === item.id}
        recordingActive={recordingDesignId !== null}
        onStartRecording={startRecording}
        onStopRecording={stopRecording}
        activeTab={activeTab}
        onChangeTab={setActiveTab}
        editedHtml={editedHtml}
        editedCss={editedCss}
        onEditHtml={setEditedHtml}
        onEditCss={setEditedCss}
        previewDoc={previewDoc}
        webViewRef={webViewRef}
        onPreviewMessage={handlePreviewMessage}
        selection={selection}
        onUpdateStyle={updateStyle}
        onUpdatePlaceholder={updatePlaceholder}
        onClearSelection={clearPreviewSelection}
        onMoveElement={moveElement}
        onMoveModule={moveModule}
        onOpenDesignStudio={() => setDesignStudioPageId(item.id)}
      />
    </ScaleDecorator>
  );

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <PhaseHeader title="UI/UX Design" subtitle="Phase 2 of 7 — Review and approve to continue" />

      <DraggableFlatList
        data={pages}
        keyExtractor={(p) => p.id}
        renderItem={renderPageItem}
        onDragEnd={({ data }) => setPageOrder(data.map((p) => p.id))}
        style={{ flex: 1 }}
        contentContainerStyle={styles.content}
        ListHeaderComponent={
          <>
            <Section icon={Palette} title="Design Style">
              <Text style={[styles.body, { color: colors.textSecondary }]}>{design.design_style}</Text>
            </Section>

            <Section icon={Palette} title="Color Palette">
              <View style={styles.colorGrid}>
                {colorEntries.map(([key, hex]) => (
                  <View key={key} style={styles.colorItem}>
                    <View style={[styles.colorSwatch, { backgroundColor: hex, borderColor: colors.border }]} />
                    <Text style={{ color: colors.textPrimary, fontSize: 11, fontWeight: "600", textTransform: "capitalize" }}>
                      {key}
                    </Text>
                    <Text style={{ color: colors.textTertiary, fontSize: 10 }}>{hex}</Text>
                  </View>
                ))}
              </View>
            </Section>

            <Section icon={Type} title="Typography">
              <Text style={[styles.body, { color: colors.textSecondary }]}>{design.typography}</Text>
            </Section>

            <Section icon={Puzzle} title="Reusable Components">
              <View style={styles.pillRow}>
                {design.components.map((component, i) => (
                  <View key={i} style={[styles.pill, { backgroundColor: colors.primaryLight }]}>
                    <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "600", textTransform: "capitalize" }}>
                      {component}
                    </Text>
                  </View>
                ))}
              </View>
            </Section>

            <Section icon={Navigation} title="Navigation Pattern">
              <Text style={[styles.body, { color: colors.textSecondary }]}>{design.navigation_pattern}</Text>
            </Section>

            <Section icon={Layout} title={`Pages (${pages.length})`}>
              <Text style={[styles.body, { color: colors.textSecondary, marginBottom: 12 }]}>
                Long-press the grip handle to drag a page and reorder it — this order is what
                codegen follows later. Upload your own mockup or screenshot for any page and
                Baby Tiger will read the image and generate matching HTML/CSS you can edit.
              </Text>

              <TextField
                label="Page name"
                placeholder="e.g. Login Screen"
                value={uploadPageName}
                onChangeText={setUploadPageName}
              />

              <View style={styles.uploadButtonRow}>
                <Pressable
                  onPress={pickFromLibrary}
                  disabled={isUploading}
                  style={[styles.uploadButton, { backgroundColor: colors.primary }, isUploading && { opacity: 0.6 }]}
                >
                  {isUploading ? <ActivityIndicator size="small" color="#fff" /> : <Upload size={15} color="#fff" />}
                  <Text style={styles.uploadButtonText}>Upload Design</Text>
                </Pressable>
                <Pressable
                  onPress={captureFromCamera}
                  disabled={isUploading}
                  style={[styles.cameraButton, { borderColor: colors.primary }, isUploading && { opacity: 0.6 }]}
                >
                  <Camera size={15} color={colors.primary} />
                  <Text style={[styles.uploadButtonText, { color: colors.primary }]}>Use Camera</Text>
                </Pressable>
              </View>
              <Pressable
                onPress={() => setIsFigmaModalOpen(true)}
                disabled={isUploading}
                style={[styles.cameraButton, { borderColor: colors.primary, marginTop: 10 }, isUploading && { opacity: 0.6 }]}
              >
                <Frame size={15} color={colors.primary} />
                <Text style={[styles.uploadButtonText, { color: colors.primary }]}>Import from Figma</Text>
              </Pressable>
            </Section>
          </>
        }
        ListEmptyComponent={
          <Text style={{ color: colors.textTertiary, fontSize: 12, marginBottom: 16 }}>No pages yet.</Text>
        }
      />

      <PhaseFooter
        note="Review the design above. Once approved, Baby Tiger moves to Architecture 🏗️"
        secondaryActions={[
          { label: "Save", icon: Save, onPress: handleSaveAll, loading: isSavingPages },
          { label: "Export Docs", icon: BookOpen, onPress: handleDownloadDocs, loading: isDownloadingDocs },
        ]}
        primaryLabel="Approve & Continue"
        primaryIcon={ThumbsUp}
        onPrimaryPress={handleApprove}
        primaryLoading={isApproving}
      />

      {designStudioPageId && (() => {
        const studioPage = pages.find((p) => p.id === designStudioPageId);
        if (!studioPage) return null;
        return (
          <DesignStudioModal
            visible
            html={studioPage.generated_html || ""}
            css={studioPage.generated_css || ""}
            onSave={(html, css) => {
              applyPageEdit(studioPage.id, html, css);
              // If this page's raw code editor is also open, keep its state
              // in sync — otherwise the next keystroke there re-fires the
              // editedHtml/editedCss sync effect with stale values and
              // silently reverts this save.
              if (expandedPageId === studioPage.id) {
                setEditedHtml(html);
                setEditedCss(css);
              }
              setDesignStudioPageId(null);
            }}
            onClose={() => setDesignStudioPageId(null)}
          />
        );
      })()}

      <Modal
        visible={isFigmaModalOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setIsFigmaModalOpen(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={[styles.modalCard, { backgroundColor: colors.surface }]}>
            <View style={styles.modalHeader}>
              <Text style={{ color: colors.textPrimary, fontSize: 14, fontWeight: "700" }}>
                Import from Figma
              </Text>
              <Pressable onPress={() => setIsFigmaModalOpen(false)} hitSlop={8}>
                <X size={18} color={colors.textSecondary} />
              </Pressable>
            </View>
            <Text style={{ color: colors.textTertiary, fontSize: 11, marginBottom: 10 }}>
              In Figma, right-click a frame → "Copy link to selection," then paste it below.
              Haven't connected Figma yet? Do that first in Settings.
            </Text>
            <TextField
              label="Figma frame link"
              placeholder="https://www.figma.com/design/..."
              value={figmaUrl}
              onChangeText={setFigmaUrl}
              autoCapitalize="none"
            />
            <TextField
              label="Page name"
              placeholder="e.g. Login Screen"
              value={uploadPageName}
              onChangeText={setUploadPageName}
            />
            <Pressable
              onPress={importFromFigma}
              disabled={isImportingFigma}
              style={[styles.modalSubmit, { backgroundColor: colors.primary }, isImportingFigma && { opacity: 0.6 }]}
            >
              {isImportingFigma ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Frame size={15} color="#fff" />
              )}
              <Text style={{ color: "#fff", fontWeight: "700", fontSize: 13 }}>Import</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

interface PageCardProps {
  page: Page;
  drag: () => void;
  isActive: boolean;
  isExpanded: boolean;
  onToggleExpand: (page: Page) => void;
  onGenerateCode: (id: string) => void;
  generatingCode: boolean;
  onDelete: (id: string) => void;
  recording: boolean;
  transcribing: boolean;
  recordingActive: boolean;
  onStartRecording: (id: string) => void;
  onStopRecording: () => void;
  activeTab: "code" | "preview";
  onChangeTab: (tab: "code" | "preview") => void;
  editedHtml: string;
  editedCss: string;
  onEditHtml: (v: string) => void;
  onEditCss: (v: string) => void;
  previewDoc: string;
  webViewRef: React.RefObject<WebView | null>;
  onPreviewMessage: (e: WebViewMessageEvent) => void;
  selection: PreviewSelection | null;
  onUpdateStyle: (prop: string, value: string) => void;
  onUpdatePlaceholder: (value: string) => void;
  onClearSelection: () => void;
  onMoveElement: (direction: "up" | "down") => void;
  onMoveModule: (direction: "up" | "down") => void;
  onOpenDesignStudio: () => void;
}

function PageCard({
  page, drag, isActive, isExpanded, onToggleExpand, onGenerateCode, generatingCode, onDelete,
  onOpenDesignStudio,
  recording, transcribing, recordingActive, onStartRecording, onStopRecording,
  activeTab, onChangeTab, editedHtml, editedCss, onEditHtml, onEditCss, previewDoc,
  webViewRef, onPreviewMessage, selection, onUpdateStyle, onUpdatePlaceholder, onClearSelection,
  onMoveElement, onMoveModule,
}: PageCardProps) {
  const { colors } = useTheme();

  return (
    <View
      style={[
        styles.designCard,
        { borderColor: colors.border, backgroundColor: isActive ? colors.surface : colors.background },
      ]}
    >
      <View style={styles.designRow}>
        <Pressable onLongPress={drag} disabled={isActive} hitSlop={8} style={styles.gripHandle}>
          <GripVertical size={16} color={colors.textTertiary} />
        </Pressable>

        {page.kind === "upload" && page.image_url ? (
          <Image source={{ uri: page.image_url }} style={[styles.thumb, { borderColor: colors.border }]} />
        ) : (
          <View style={[styles.thumb, styles.thumbPlaceholder, { borderColor: colors.border }]}>
            <Layout size={18} color={colors.textTertiary} />
          </View>
        )}

        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Text style={[styles.designName, { color: colors.textPrimary }]} numberOfLines={1}>
              {page.name}
            </Text>
            <View style={[styles.kindBadge, { borderColor: colors.border }]}>
              <Text style={{ color: colors.textTertiary, fontSize: 9, fontWeight: "600" }}>
                {page.kind === "screen" ? "AI" : "Your upload"}
              </Text>
            </View>
          </View>
          {page.purpose && (
            <Text style={{ color: colors.textSecondary, fontSize: 11 }} numberOfLines={1}>
              {page.purpose}
            </Text>
          )}
          {page.generated_html ? (
            <View style={{ marginTop: 4 }}>
              <ModuleTags modules={page.modules} />
            </View>
          ) : page.kind === "screen" ? (
            <View style={{ marginTop: 4 }}>
              <ModuleTags modules={page.key_elements} />
            </View>
          ) : (
            <Text style={{ color: colors.textTertiary, fontSize: 11, fontStyle: "italic" }}>
              Not analyzed yet — generate code to see a preview
            </Text>
          )}
          {page.voice_note_url && (
            <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 }}>
              <FileAudio size={11} color={colors.primary} />
              <Text style={{ color: colors.primary, fontSize: 11 }}>
                {page.voice_note_transcript ? "Voice note attached" : "Voice note (transcription failed)"}
              </Text>
            </View>
          )}
        </View>
      </View>

      <View style={styles.designActions}>
        {page.kind === "upload" && (
          recording ? (
            <Pressable onPress={onStopRecording} style={[styles.pillButton, { backgroundColor: colors.error }]}>
              <Square size={13} color="#fff" />
              <Text style={styles.pillButtonText}>Stop</Text>
            </Pressable>
          ) : (
            <Pressable
              onPress={() => onStartRecording(page.id)}
              disabled={transcribing || recordingActive}
              style={[styles.iconButton, { borderColor: colors.border }, (transcribing || recordingActive) && { opacity: 0.5 }]}
            >
              {transcribing ? (
                <ActivityIndicator size="small" color={colors.textSecondary} />
              ) : (
                <Mic size={14} color={colors.textSecondary} />
              )}
            </Pressable>
          )
        )}

        {page.generated_html ? (
          <Pressable
            onPress={() => onToggleExpand(page)}
            style={[styles.pillButton, { borderColor: colors.border, borderWidth: 1 }]}
          >
            <Code2 size={13} color={colors.textPrimary} />
            <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "600" }}>
              {isExpanded ? "Hide code" : "View/edit"}
            </Text>
          </Pressable>
        ) : page.kind === "upload" ? (
          <Pressable
            onPress={() => onGenerateCode(page.id)}
            disabled={generatingCode}
            style={[styles.pillButton, { backgroundColor: colors.primary }, generatingCode && { opacity: 0.6 }]}
          >
            {generatingCode ? <ActivityIndicator size="small" color="#fff" /> : <Wand2 size={13} color="#fff" />}
            <Text style={styles.pillButtonText}>Generate</Text>
          </Pressable>
        ) : null}

        <Pressable
          onPress={onOpenDesignStudio}
          style={[styles.pillButton, { borderColor: colors.primary, borderWidth: 1 }]}
        >
          <LayoutTemplate size={13} color={colors.primary} />
          <Text style={{ color: colors.primary, fontSize: 12, fontWeight: "600" }}>Design Studio</Text>
        </Pressable>

        {page.kind === "upload" && (
          <Pressable onPress={() => onDelete(page.id)} style={[styles.iconButton, { borderColor: colors.border }]}>
            <Trash2 size={14} color={colors.error} />
          </Pressable>
        )}
      </View>

      {isExpanded && (
        <View style={[styles.expandedBox, { borderTopColor: colors.border }]}>
          {page.generation_notes && (
            <View style={{ flexDirection: "row", gap: 6, marginBottom: 10 }}>
              <ImageIcon size={13} color={colors.textTertiary} />
              <Text style={{ color: colors.textTertiary, fontSize: 11, fontStyle: "italic", flex: 1 }}>
                {page.generation_notes}
              </Text>
            </View>
          )}
          {page.voice_note_transcript && (
            <View style={[styles.transcriptBox, { backgroundColor: colors.surface, borderColor: colors.border }]}>
              <Text style={{ color: colors.textSecondary, fontSize: 11, fontWeight: "600", marginBottom: 4 }}>
                Voice note transcript
              </Text>
              <Text style={{ color: colors.textTertiary, fontSize: 11, fontStyle: "italic" }}>
                "{page.voice_note_transcript}"
              </Text>
            </View>
          )}

          <View style={styles.tabRow}>
            <Pressable
              onPress={() => onChangeTab("preview")}
              style={[styles.tabButton, activeTab === "preview" && { backgroundColor: colors.primaryLight }]}
            >
              <Eye size={13} color={activeTab === "preview" ? colors.primary : colors.textSecondary} />
              <Text style={{ color: activeTab === "preview" ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>
                Preview
              </Text>
            </Pressable>
            <Pressable
              onPress={() => onChangeTab("code")}
              style={[styles.tabButton, activeTab === "code" && { backgroundColor: colors.primaryLight }]}
            >
              <Code2 size={13} color={activeTab === "code" ? colors.primary : colors.textSecondary} />
              <Text style={{ color: activeTab === "code" ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>
                Code
              </Text>
            </Pressable>
          </View>

          {activeTab === "code" ? (
            <>
              <Text style={[styles.codeLabel, { color: colors.textSecondary }]}>HTML</Text>
              <TextInput
                value={editedHtml}
                onChangeText={onEditHtml}
                multiline
                style={[styles.codeInput, { color: colors.textPrimary, backgroundColor: colors.surface, borderColor: colors.border }]}
              />
              <Text style={[styles.codeLabel, { color: colors.textSecondary }]}>CSS</Text>
              <TextInput
                value={editedCss}
                onChangeText={onEditCss}
                multiline
                style={[styles.codeInput, { color: colors.textPrimary, backgroundColor: colors.surface, borderColor: colors.border }]}
              />
            </>
          ) : (
            <View style={{ marginBottom: 10 }}>
              <Text style={{ color: colors.textTertiary, fontSize: 11, marginBottom: 6 }}>
                Tap any element to edit it directly.
              </Text>
              <View style={[styles.previewBox, { borderColor: colors.border }]}>
                <WebView
                  ref={webViewRef}
                  source={{ html: previewDoc }}
                  onMessage={onPreviewMessage}
                  style={{ flex: 1 }}
                  originWhitelist={["*"]}
                />

                {selection && (
                  <View style={[styles.selectionPanel, { borderColor: colors.border, backgroundColor: colors.surface }]}>
                  <ScrollView showsVerticalScrollIndicator={false}>
                    <View style={styles.selectionHeaderRow}>
                      <View style={[styles.tagBadge, { backgroundColor: colors.background }]}>
                        <Text style={{ color: colors.textTertiary, fontSize: 10, fontFamily: "monospace" }}>{selection.tag}</Text>
                      </View>
                      <Pressable onPress={onClearSelection} hitSlop={8}>
                        <X size={14} color={colors.textTertiary} />
                      </Pressable>
                    </View>

                    {selection.isField ? (
                      <View style={{ marginBottom: 8 }}>
                        <Text style={{ color: colors.textTertiary, fontSize: 10, marginBottom: 4 }}>Placeholder</Text>
                        <TextInput
                          value={selection.placeholder ?? ""}
                          onChangeText={onUpdatePlaceholder}
                          style={[styles.panelInput, { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.background }]}
                        />
                      </View>
                    ) : (
                      <Text style={{ color: colors.textTertiary, fontSize: 10, fontStyle: "italic", marginBottom: 8 }}>
                        Tap the text in the preview above to edit it.
                      </Text>
                    )}

                    <View style={{ flexDirection: "row", gap: 8, marginBottom: 8 }}>
                      <View style={{ flex: 1 }}>
                        <Text style={{ color: colors.textTertiary, fontSize: 10, marginBottom: 4 }}>Text color</Text>
                        <TextInput
                          value={selection.styles.color || ""}
                          onChangeText={(v) => onUpdateStyle("color", v)}
                          placeholder="#000000"
                          placeholderTextColor={colors.textTertiary}
                          autoCapitalize="none"
                          style={[styles.panelInput, { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.background }]}
                        />
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={{ color: colors.textTertiary, fontSize: 10, marginBottom: 4 }}>Background</Text>
                        <TextInput
                          value={selection.styles.backgroundColor || ""}
                          onChangeText={(v) => onUpdateStyle("backgroundColor", v)}
                          placeholder="transparent"
                          placeholderTextColor={colors.textTertiary}
                          autoCapitalize="none"
                          style={[styles.panelInput, { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.background }]}
                        />
                      </View>
                    </View>

                    <View style={{ flexDirection: "row", gap: 8, marginBottom: 8 }}>
                      <View style={{ flex: 1 }}>
                        <Text style={{ color: colors.textTertiary, fontSize: 10, marginBottom: 4 }}>Width</Text>
                        <TextInput
                          value={selection.styles.width ?? ""}
                          onChangeText={(v) => onUpdateStyle("width", v)}
                          placeholder="e.g. 200px"
                          placeholderTextColor={colors.textTertiary}
                          autoCapitalize="none"
                          style={[styles.panelInput, { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.background }]}
                        />
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={{ color: colors.textTertiary, fontSize: 10, marginBottom: 4 }}>Height</Text>
                        <TextInput
                          value={selection.styles.height ?? ""}
                          onChangeText={(v) => onUpdateStyle("height", v)}
                          placeholder="e.g. 48px"
                          placeholderTextColor={colors.textTertiary}
                          autoCapitalize="none"
                          style={[styles.panelInput, { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.background }]}
                        />
                      </View>
                    </View>

                    <View style={{ marginBottom: 8 }}>
                      <Text style={{ color: colors.textTertiary, fontSize: 10, marginBottom: 4 }}>Corner radius</Text>
                      <TextInput
                        value={selection.styles.borderRadius ?? ""}
                        onChangeText={(v) => onUpdateStyle("borderRadius", v)}
                        placeholder="e.g. 8px, 9999px"
                        placeholderTextColor={colors.textTertiary}
                        autoCapitalize="none"
                        style={[styles.panelInput, { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.background }]}
                      />
                    </View>

                    <View style={{ flexDirection: "row", gap: 8, marginBottom: 8 }}>
                      <Pressable
                        onPress={() =>
                          onUpdateStyle(
                            "fontWeight",
                            selection.styles.fontWeight === "bold" || parseInt(selection.styles.fontWeight, 10) >= 700
                              ? "400"
                              : "700"
                          )
                        }
                        style={[
                          styles.smallToggle,
                          { borderColor: colors.border },
                          (selection.styles.fontWeight === "bold" || parseInt(selection.styles.fontWeight, 10) >= 700) && {
                            borderColor: colors.primary,
                            backgroundColor: colors.primaryLight,
                          },
                        ]}
                      >
                        <Text style={{ fontWeight: "800", fontSize: 12, color: colors.textPrimary }}>B</Text>
                      </Pressable>
                      {(["left", "center", "right"] as const).map((align) => (
                        <Pressable
                          key={align}
                          onPress={() => onUpdateStyle("textAlign", align)}
                          style={[
                            styles.smallToggle,
                            { borderColor: colors.border },
                            selection.styles.textAlign === align && { borderColor: colors.primary, backgroundColor: colors.primaryLight },
                          ]}
                        >
                          <Text style={{ fontSize: 9, color: colors.textPrimary, textTransform: "capitalize" }}>{align}</Text>
                        </Pressable>
                      ))}
                    </View>

                    <View style={styles.moveRow}>
                      <Pressable onPress={() => onMoveElement("up")} style={[styles.moveButton, { borderColor: colors.border }]}>
                        <Text style={{ color: colors.textSecondary, fontSize: 10 }}>↑ Element</Text>
                      </Pressable>
                      <Pressable onPress={() => onMoveElement("down")} style={[styles.moveButton, { borderColor: colors.border }]}>
                        <Text style={{ color: colors.textSecondary, fontSize: 10 }}>↓ Element</Text>
                      </Pressable>
                    </View>

                    {selection.module && (
                      <>
                        <Text style={{ color: colors.textTertiary, fontSize: 10, marginTop: 8, marginBottom: 4 }}>
                          Module: {selection.module}
                        </Text>
                        <View style={styles.moveRow}>
                          <Pressable onPress={() => onMoveModule("up")} style={[styles.moveButton, { borderColor: colors.border }]}>
                            <Text style={{ color: colors.textSecondary, fontSize: 10 }}>↑ Module</Text>
                          </Pressable>
                          <Pressable onPress={() => onMoveModule("down")} style={[styles.moveButton, { borderColor: colors.border }]}>
                            <Text style={{ color: colors.textSecondary, fontSize: 10 }}>↓ Module</Text>
                          </Pressable>
                        </View>
                      </>
                    )}
                  </ScrollView>
                  </View>
                )}
              </View>
            </View>
          )}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  content: { padding: 16 },
  body: { fontSize: 13, lineHeight: 19 },
  colorGrid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  colorItem: { alignItems: "center", width: 64, gap: 4 },
  colorSwatch: { width: 48, height: 48, borderRadius: 12, borderWidth: 1 },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 10 },
  elementPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, borderWidth: 1 },
  uploadButtonRow: { flexDirection: "row", gap: 10 },
  uploadButton: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: 12, paddingVertical: 12 },
  cameraButton: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: 12, paddingVertical: 12, borderWidth: 1 },
  uploadButtonText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  designCard: { borderWidth: 1, borderRadius: 14, padding: 12, marginBottom: 10 },
  designRow: { flexDirection: "row", gap: 10, alignItems: "center" },
  gripHandle: { paddingRight: 2 },
  thumb: { width: 52, height: 52, borderRadius: 10, borderWidth: 1 },
  thumbPlaceholder: { alignItems: "center", justifyContent: "center" },
  designName: { fontSize: 13, fontWeight: "600" },
  kindBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, borderWidth: 1 },
  designActions: { flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" },
  iconButton: { width: 34, height: 34, borderRadius: 10, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  pillButton: { flexDirection: "row", alignItems: "center", gap: 5, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
  pillButtonText: { color: "#fff", fontWeight: "700", fontSize: 12 },
  expandedBox: { borderTopWidth: StyleSheet.hairlineWidth, marginTop: 12, paddingTop: 12 },
  transcriptBox: { borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 10 },
  codeLabel: { fontSize: 11, fontWeight: "600", marginBottom: 4 },
  codeInput: { borderWidth: 1, borderRadius: 10, padding: 10, fontSize: 11, fontFamily: "monospace", minHeight: 100, textAlignVertical: "top", marginBottom: 10 },
  tabRow: { flexDirection: "row", gap: 6, marginBottom: 10 },
  tabButton: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 8 },
  previewBox: { height: 360, borderRadius: 10, borderWidth: 1, overflow: "hidden", position: "relative" },
  selectionPanel: { position: "absolute", top: 8, right: 8, width: 190, maxHeight: 340, borderRadius: 10, borderWidth: 1, padding: 10 },
  selectionHeaderRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  tagBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6 },
  panelInput: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 6, fontSize: 11 },
  smallToggle: { flex: 1, borderWidth: 1, borderRadius: 8, paddingVertical: 7, alignItems: "center", justifyContent: "center" },
  moveRow: { flexDirection: "row", gap: 8 },
  moveButton: { flex: 1, borderWidth: 1, borderRadius: 8, paddingVertical: 7, alignItems: "center", justifyContent: "center" },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.7)", alignItems: "center", justifyContent: "center", padding: 24 },
  modalCard: { width: "100%", maxWidth: 480, borderRadius: 16, padding: 16 },
  modalHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  modalSubmit: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, borderRadius: 12, paddingVertical: 12, marginTop: 4 },
});
