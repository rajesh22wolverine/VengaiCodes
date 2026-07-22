import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import { RecordingPresets, requestRecordingPermissionsAsync, setAudioModeAsync, useAudioRecorder } from "expo-audio";
import { WebView, type WebViewMessageEvent } from "react-native-webview";
import {
  BookOpen, Camera, Code2, Eye, FileAudio, ImageIcon, Layout, Mic, Navigation, Palette,
  Puzzle, Save, Square, ThumbsUp, Trash2, Type, Upload, Wand2, X,
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

function guessImageMimeType(asset: ImagePicker.ImagePickerAsset): string {
  if (asset.mimeType) return asset.mimeType;
  const ext = asset.uri.split(".").pop()?.toLowerCase();
  if (ext === "png") return "image/png";
  if (ext === "webp") return "image/webp";
  return "image/jpeg";
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
  const [expandedDesignId, setExpandedDesignId] = useState<string | null>(null);
  const [editedHtml, setEditedHtml] = useState("");
  const [editedCss, setEditedCss] = useState("");
  const [isSavingCode, setIsSavingCode] = useState(false);

  const [recordingDesignId, setRecordingDesignId] = useState<string | null>(null);
  const [transcribingDesignId, setTranscribingDesignId] = useState<string | null>(null);
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recordingDesignIdRef = useRef<string | null>(null);

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
      const { data } = await apiClient.post("/uiux/generate", { project_id: projectId });
      setDesign(data.design);
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
      setExpandedDesignId(designId);
      showToast("Code generated from your design! 🐯✨");
    } catch (error: any) {
      showToast(error.message || "Failed to generate code from design.", "error");
    } finally {
      setGeneratingCodeFor(null);
    }
  };

  const handleExpandDesign = (d: UploadedDesign) => {
    if (expandedDesignId === d.id) {
      setExpandedDesignId(null);
      setSelection(null);
      return;
    }
    setEditedHtml(d.generated_html || "");
    setEditedCss(d.generated_css || "");
    setSelection(null);
    setPreviewDoc(buildPreviewDocument(d.generated_html || "", d.generated_css || ""));
    setActiveTab("preview");
    setExpandedDesignId(d.id);
  };

  const handleSaveCode = async (designId: string) => {
    setIsSavingCode(true);
    try {
      const { data } = await apiClient.put(`/uiux/${projectId}/design/${designId}/code`, {
        html: editedHtml,
        css: editedCss,
      });
      setUploadedDesigns((prev) => prev.map((d) => (d.id === designId ? data.design : d)));
      showToast("Changes saved 🐯");
    } catch (error: any) {
      showToast(error.message || "Failed to save changes.", "error");
    } finally {
      setIsSavingCode(false);
    }
  };

  const handleDeleteDesign = async (designId: string) => {
    try {
      await apiClient.delete(`/uiux/${projectId}/design/${designId}`);
      setUploadedDesigns((prev) => prev.filter((d) => d.id !== designId));
      if (expandedDesignId === designId) setExpandedDesignId(null);
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

  return (
    <View style={[styles.screen, { backgroundColor: colors.background }]}>
      <PhaseHeader title="UI/UX Design" subtitle="Phase 2 of 7 — Review and approve to continue" />

      <ScrollView contentContainerStyle={styles.content}>
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

        <Section icon={Layout} title={`Screens (${design.screens.length})`}>
          {design.screens.map((screen, i) => (
            <View key={i} style={[styles.screenCard, { backgroundColor: colors.background, borderColor: colors.border }]}>
              <View style={styles.screenHeaderRow}>
                <View style={[styles.dot, { backgroundColor: design.color_palette.primary }]} />
                <Text style={[styles.screenName, { color: colors.textPrimary }]}>{screen.name}</Text>
              </View>
              <Text style={[styles.body, { color: colors.textSecondary, marginBottom: 8 }]}>{screen.purpose}</Text>
              <View style={styles.pillRow}>
                {screen.key_elements.map((el, j) => (
                  <View key={j} style={[styles.elementPill, { backgroundColor: colors.surface, borderColor: colors.border }]}>
                    <Text style={{ color: colors.textTertiary, fontSize: 11 }}>{el}</Text>
                  </View>
                ))}
              </View>
            </View>
          ))}
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

        <Section icon={Upload} title="Upload Your Own Page Design">
          <Text style={[styles.body, { color: colors.textSecondary, marginBottom: 12 }]}>
            Have a mockup or screenshot for a page? Upload it — or snap a photo of a sketch — and
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

          {uploadedDesigns.length === 0 ? (
            <Text style={{ color: colors.textTertiary, fontSize: 12, marginTop: 12 }}>No designs uploaded yet.</Text>
          ) : (
            <View style={{ marginTop: 12, gap: 10 }}>
              {uploadedDesigns.map((d) => (
                <View key={d.id} style={[styles.designCard, { borderColor: colors.border, backgroundColor: colors.background }]}>
                  <View style={styles.designRow}>
                    <Image source={{ uri: d.image_url }} style={[styles.thumb, { borderColor: colors.border }]} />
                    <View style={{ flex: 1 }}>
                      <Text style={[styles.designName, { color: colors.textPrimary }]} numberOfLines={1}>
                        {d.page_name}
                      </Text>
                      <Text style={{ color: colors.textTertiary, fontSize: 11 }}>
                        {d.generated_html ? "Code generated" : "Not converted yet"}
                      </Text>
                      {d.voice_note_url && (
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 4, marginTop: 2 }}>
                          <FileAudio size={11} color={colors.primary} />
                          <Text style={{ color: colors.primary, fontSize: 11 }}>
                            {d.voice_note_transcript ? "Voice note attached" : "Voice note (transcription failed)"}
                          </Text>
                        </View>
                      )}
                    </View>
                  </View>

                  <View style={styles.designActions}>
                    {recordingDesignId === d.id ? (
                      <Pressable onPress={stopRecording} style={[styles.pillButton, { backgroundColor: colors.error }]}>
                        <Square size={13} color="#fff" />
                        <Text style={styles.pillButtonText}>Stop</Text>
                      </Pressable>
                    ) : (
                      <Pressable
                        onPress={() => startRecording(d.id)}
                        disabled={transcribingDesignId === d.id || recordingDesignId !== null}
                        style={[
                          styles.iconButton,
                          { borderColor: colors.border },
                          (transcribingDesignId === d.id || (recordingDesignId !== null && recordingDesignId !== d.id)) && { opacity: 0.5 },
                        ]}
                      >
                        {transcribingDesignId === d.id ? (
                          <ActivityIndicator size="small" color={colors.textSecondary} />
                        ) : (
                          <Mic size={14} color={colors.textSecondary} />
                        )}
                      </Pressable>
                    )}

                    {d.generated_html ? (
                      <Pressable
                        onPress={() => handleExpandDesign(d)}
                        style={[styles.pillButton, { borderColor: colors.border, borderWidth: 1 }]}
                      >
                        <Code2 size={13} color={colors.textPrimary} />
                        <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "600" }}>
                          {expandedDesignId === d.id ? "Hide code" : "View/edit"}
                        </Text>
                      </Pressable>
                    ) : (
                      <Pressable
                        onPress={() => handleGenerateCode(d.id)}
                        disabled={generatingCodeFor === d.id}
                        style={[styles.pillButton, { backgroundColor: colors.primary }, generatingCodeFor === d.id && { opacity: 0.6 }]}
                      >
                        {generatingCodeFor === d.id ? (
                          <ActivityIndicator size="small" color="#fff" />
                        ) : (
                          <Wand2 size={13} color="#fff" />
                        )}
                        <Text style={styles.pillButtonText}>Generate</Text>
                      </Pressable>
                    )}

                    <Pressable onPress={() => handleDeleteDesign(d.id)} style={[styles.iconButton, { borderColor: colors.border }]}>
                      <Trash2 size={14} color={colors.error} />
                    </Pressable>
                  </View>

                  {expandedDesignId === d.id && (
                    <View style={[styles.expandedBox, { borderTopColor: colors.border }]}>
                      {d.generation_notes && (
                        <View style={{ flexDirection: "row", gap: 6, marginBottom: 10 }}>
                          <ImageIcon size={13} color={colors.textTertiary} />
                          <Text style={{ color: colors.textTertiary, fontSize: 11, fontStyle: "italic", flex: 1 }}>
                            {d.generation_notes}
                          </Text>
                        </View>
                      )}
                      {d.voice_note_transcript && (
                        <View style={[styles.transcriptBox, { backgroundColor: colors.surface, borderColor: colors.border }]}>
                          <Text style={{ color: colors.textSecondary, fontSize: 11, fontWeight: "600", marginBottom: 4 }}>
                            Voice note transcript
                          </Text>
                          <Text style={{ color: colors.textTertiary, fontSize: 11, fontStyle: "italic" }}>
                            "{d.voice_note_transcript}"
                          </Text>
                        </View>
                      )}

                      <View style={styles.tabRow}>
                        <Pressable
                          onPress={() => setActiveTab("preview")}
                          style={[styles.tabButton, activeTab === "preview" && { backgroundColor: colors.primaryLight }]}
                        >
                          <Eye size={13} color={activeTab === "preview" ? colors.primary : colors.textSecondary} />
                          <Text style={{ color: activeTab === "preview" ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>
                            Preview
                          </Text>
                        </Pressable>
                        <Pressable
                          onPress={() => setActiveTab("code")}
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
                            onChangeText={setEditedHtml}
                            multiline
                            style={[styles.codeInput, { color: colors.textPrimary, backgroundColor: colors.surface, borderColor: colors.border }]}
                          />
                          <Text style={[styles.codeLabel, { color: colors.textSecondary }]}>CSS</Text>
                          <TextInput
                            value={editedCss}
                            onChangeText={setEditedCss}
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
                              onMessage={handlePreviewMessage}
                              style={{ flex: 1 }}
                              originWhitelist={["*"]}
                            />

                            {selection && (
                              <View style={[styles.selectionPanel, { borderColor: colors.border, backgroundColor: colors.surface }]}>
                                <View style={styles.selectionHeaderRow}>
                                  <View style={[styles.tagBadge, { backgroundColor: colors.background }]}>
                                    <Text style={{ color: colors.textTertiary, fontSize: 10, fontFamily: "monospace" }}>{selection.tag}</Text>
                                  </View>
                                  <Pressable onPress={clearPreviewSelection} hitSlop={8}>
                                    <X size={14} color={colors.textTertiary} />
                                  </Pressable>
                                </View>

                                {selection.isField ? (
                                  <View style={{ marginBottom: 8 }}>
                                    <Text style={{ color: colors.textTertiary, fontSize: 10, marginBottom: 4 }}>Placeholder</Text>
                                    <TextInput
                                      value={selection.placeholder ?? ""}
                                      onChangeText={updatePlaceholder}
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
                                      onChangeText={(v) => updateStyle("color", v)}
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
                                      onChangeText={(v) => updateStyle("backgroundColor", v)}
                                      placeholder="transparent"
                                      placeholderTextColor={colors.textTertiary}
                                      autoCapitalize="none"
                                      style={[styles.panelInput, { color: colors.textPrimary, borderColor: colors.border, backgroundColor: colors.background }]}
                                    />
                                  </View>
                                </View>

                                <View style={{ flexDirection: "row", gap: 8 }}>
                                  <Pressable
                                    onPress={() =>
                                      updateStyle(
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
                                      onPress={() => updateStyle("textAlign", align)}
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
                              </View>
                            )}
                          </View>
                        </View>
                      )}

                      <Pressable
                        onPress={() => handleSaveCode(d.id)}
                        disabled={isSavingCode}
                        style={[styles.saveButton, { backgroundColor: colors.primary }, isSavingCode && { opacity: 0.6 }]}
                      >
                        {isSavingCode ? <ActivityIndicator size="small" color="#fff" /> : <Save size={13} color="#fff" />}
                        <Text style={styles.pillButtonText}>Save Changes</Text>
                      </Pressable>
                    </View>
                  )}
                </View>
              ))}
            </View>
          )}
        </Section>
      </ScrollView>

      <PhaseFooter
        note="Review the design above. Once approved, Baby Tiger moves to Architecture 🏗️"
        secondaryActions={[{ label: "Export Docs", icon: BookOpen, onPress: handleDownloadDocs, loading: isDownloadingDocs }]}
        primaryLabel="Approve & Continue"
        primaryIcon={ThumbsUp}
        onPrimaryPress={handleApprove}
        primaryLoading={isApproving}
      />
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
  screenCard: { borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 10 },
  screenHeaderRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  screenName: { fontSize: 13, fontWeight: "700" },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 10 },
  elementPill: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, borderWidth: 1 },
  uploadButtonRow: { flexDirection: "row", gap: 10 },
  uploadButton: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: 12, paddingVertical: 12 },
  cameraButton: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: 12, paddingVertical: 12, borderWidth: 1 },
  uploadButtonText: { color: "#fff", fontWeight: "700", fontSize: 13 },
  designCard: { borderWidth: 1, borderRadius: 14, padding: 12 },
  designRow: { flexDirection: "row", gap: 10, alignItems: "center" },
  thumb: { width: 52, height: 52, borderRadius: 10, borderWidth: 1 },
  designName: { fontSize: 13, fontWeight: "600" },
  designActions: { flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" },
  iconButton: { width: 34, height: 34, borderRadius: 10, borderWidth: 1, alignItems: "center", justifyContent: "center" },
  pillButton: { flexDirection: "row", alignItems: "center", gap: 5, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8 },
  pillButtonText: { color: "#fff", fontWeight: "700", fontSize: 12 },
  expandedBox: { borderTopWidth: StyleSheet.hairlineWidth, marginTop: 12, paddingTop: 12 },
  transcriptBox: { borderWidth: 1, borderRadius: 10, padding: 10, marginBottom: 10 },
  codeLabel: { fontSize: 11, fontWeight: "600", marginBottom: 4 },
  codeInput: { borderWidth: 1, borderRadius: 10, padding: 10, fontSize: 11, fontFamily: "monospace", minHeight: 100, textAlignVertical: "top", marginBottom: 10 },
  saveButton: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: 10, paddingVertical: 10 },
  tabRow: { flexDirection: "row", gap: 6, marginBottom: 10 },
  tabButton: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 8 },
  previewBox: { height: 360, borderRadius: 10, borderWidth: 1, overflow: "hidden", position: "relative" },
  selectionPanel: { position: "absolute", top: 8, right: 8, width: 190, borderRadius: 10, borderWidth: 1, padding: 10 },
  selectionHeaderRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  tagBadge: { paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6 },
  panelInput: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 6, fontSize: 11 },
  smallToggle: { flex: 1, borderWidth: 1, borderRadius: 8, paddingVertical: 7, alignItems: "center", justifyContent: "center" },
});
