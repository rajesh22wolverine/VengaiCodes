// ─── Scan QR — the receiving side of Share via QR ───
//
// One scanner for all three kinds of VengaiCode code (see
// src/lib/qrTransfer.ts for the formats):
//   link       → offer to open it in the browser (that downloads the ZIP)
//   blueprint  → show what's in it, then import it as a new project
//   sequence   → keep scanning; every new code fills the progress bar, and
//                once all are in, rebuild the ZIP and hand it to the share
//                sheet (Files, Drive, a chat…)
// A picture of a code (a saved blueprint image) works too, via
// expo-camera's scanFromURLAsync.

import { useCallback, useRef, useState } from "react";
import { ActivityIndicator, Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { router } from "expo-router";
import { CameraView, scanFromURLAsync, useCameraPermissions } from "expo-camera";
import * as ImagePicker from "expo-image-picker";
import { File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import { AlertTriangle, CheckCircle2, ExternalLink, ImagePlus, Layers, QrCode, RotateCcw } from "lucide-react-native";

import apiClient from "@/lib/api";
import { SequenceCollector, buildZip, classifyScan, decodeBundle, zipFileName } from "@/lib/qrTransfer";
import { useAppDispatch } from "@/store/hooks";
import { fetchProjects } from "@/store/slices/projectSlice";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";

const WARNING = "#eab308";

type Found =
  | { kind: "link"; url: string }
  | {
      kind: "blueprint";
      text: string;
      info?: { name: string; description: string; stack: Record<string, string>; table_names: string[]; endpoint_count: number };
      error?: string;
    }
  | { kind: "saved"; name: string; fileCount: number; uri: string }
  | { kind: "error"; message: string };

export default function ScanScreen() {
  const { colors } = useTheme();
  const { showToast } = useToast();
  const dispatch = useAppDispatch();
  const [permission, requestPermission] = useCameraPermissions();
  const [found, setFound] = useState<Found | null>(null);
  const [progress, setProgress] = useState<{ received: number; count: number } | null>(null);
  const [otherTransfer, setOtherTransfer] = useState(false);
  const [working, setWorking] = useState(false);
  const collector = useRef(new SequenceCollector());
  // onBarcodeScanned fires many times a second for the same code — once a
  // single-code result is on screen, further scans are ignored.
  const paused = useRef(false);

  const reset = () => {
    collector.current = new SequenceCollector();
    setProgress(null);
    setOtherTransfer(false);
    setFound(null);
    paused.current = false;
  };

  const finishSequence = useCallback(async () => {
    paused.current = true;
    setWorking(true);
    try {
      const bundle = decodeBundle(collector.current.assemble());
      const file = new File(Paths.cache, zipFileName(bundle.name));
      file.create({ overwrite: true });
      file.write(buildZip(bundle.files));
      setFound({ kind: "saved", name: bundle.name, fileCount: bundle.files.length, uri: file.uri });
      if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(file.uri, { mimeType: "application/zip", dialogTitle: "Save the project" });
      }
    } catch (e: any) {
      setFound({ kind: "error", message: e.message || "The codes couldn't be put back together — scan again." });
    } finally {
      setWorking(false);
    }
  }, []);

  const inspectBlueprint = async (text: string) => {
    setFound({ kind: "blueprint", text });
    try {
      const { data } = await apiClient.post("/share/blueprint/inspect", { text });
      setFound({ kind: "blueprint", text, info: data });
    } catch (e: any) {
      setFound({ kind: "blueprint", text, error: e.message || "That blueprint couldn't be read." });
    }
  };

  const handleText = useCallback(
    (raw: string) => {
      if (paused.current) return;
      const text = raw.trim();
      const kind = classifyScan(text);
      if (kind === "sequence") {
        const result = collector.current.add(text);
        if (result.otherTransfer) {
          setOtherTransfer(true);
          return;
        }
        if (result.isNew) {
          setProgress({ received: collector.current.received, count: collector.current.count });
          if (collector.current.complete) finishSequence();
        }
        return;
      }
      if (collector.current.received > 0) return; // mid-sequence: ignore stray codes
      paused.current = true;
      if (kind === "link") setFound({ kind: "link", url: text });
      else if (kind === "blueprint") inspectBlueprint(text);
      else setFound({ kind: "error", message: "That isn't a VengaiCode QR code." });
    },
    [finishSequence]
  );

  const pickImage = async () => {
    const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 1 });
    if (picked.canceled || !picked.assets?.[0]) return;
    try {
      const results = await scanFromURLAsync(picked.assets[0].uri, ["qr"]);
      if (!results.length) {
        showToast("No QR code found in that picture.", "error");
        return;
      }
      paused.current = false;
      handleText(results[0].data);
    } catch {
      showToast("That picture couldn't be read.", "error");
    }
  };

  const importBlueprint = async (text: string) => {
    setWorking(true);
    try {
      const { data } = await apiClient.post("/share/blueprint/import", { text });
      showToast(`Imported “${data.name}” 🐯`);
      dispatch(fetchProjects());
      router.replace(`/(app)/project/${data.project_id}/architecture` as any);
    } catch (e: any) {
      showToast(e.message || "Couldn't import the blueprint.", "error");
    } finally {
      setWorking(false);
    }
  };

  if (!permission) {
    return (
      <View style={[styles.center, { backgroundColor: colors.background }]}>
        <ActivityIndicator color={colors.primary} />
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={[styles.center, { backgroundColor: colors.background }]}>
        <QrCode size={40} color={colors.primary} />
        <Text style={[styles.title, { color: colors.textPrimary }]}>Scan a VengaiCode QR code</Text>
        <Text style={[styles.body, { color: colors.textSecondary }]}>
          The camera is needed to read download links, blueprints and QR sequences.
        </Text>
        <Pressable onPress={requestPermission} style={[styles.primary, { backgroundColor: colors.primary }]}>
          <Text style={styles.primaryText}>Allow camera</Text>
        </Pressable>
        <Pressable onPress={pickImage} style={[styles.outline, { borderColor: colors.border }]}>
          <ImagePlus size={15} color={colors.textPrimary} />
          <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>Read a picture instead</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={[styles.screen, { backgroundColor: "#000" }]}>
      <CameraView
        style={StyleSheet.absoluteFill}
        facing="back"
        barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
        onBarcodeScanned={found ? undefined : (result) => handleText(result.data)}
      />

      <View style={styles.frameGuide} pointerEvents="none" />

      <View style={[styles.panel, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        {!found && !progress && (
          <>
            <Text style={[styles.title, { color: colors.textPrimary }]}>Point at a VengaiCode QR code</Text>
            <Text style={[styles.body, { color: colors.textSecondary }]}>
              A download link, a blueprint, or a QR sequence playing on another screen.
            </Text>
            <Pressable onPress={pickImage} style={[styles.outline, { borderColor: colors.border }]}>
              <ImagePlus size={15} color={colors.textPrimary} />
              <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>Read a picture instead</Text>
            </Pressable>
          </>
        )}

        {progress && !found && (
          <>
            <View style={styles.row}>
              <Layers size={18} color={colors.primary} />
              <Text style={[styles.title, { color: colors.textPrimary, marginBottom: 0 }]}>
                Receiving… {progress.received} of {progress.count} codes
              </Text>
            </View>
            <View style={[styles.bar, { backgroundColor: colors.border }]}>
              <View style={[styles.barFill, { backgroundColor: colors.primary, width: `${(progress.received / progress.count) * 100}%` }]} />
            </View>
            <Text style={[styles.body, { color: colors.textSecondary }]}>
              Keep the phone steady — the codes loop, so any you miss come round again.
            </Text>
            {working && <ActivityIndicator color={colors.primary} />}
            {otherTransfer && (
              <View style={[styles.note, { borderColor: WARNING }]}>
                <AlertTriangle size={14} color={WARNING} />
                <Text style={{ color: colors.textSecondary, fontSize: 12, flex: 1 }}>
                  A different sequence is showing now (maybe its code size changed).
                </Text>
                <Pressable onPress={reset}>
                  <Text style={{ color: colors.primary, fontWeight: "700", fontSize: 12 }}>Start over</Text>
                </Pressable>
              </View>
            )}
          </>
        )}

        {found?.kind === "link" && (
          <>
            <Text style={[styles.title, { color: colors.textPrimary }]}>Download link</Text>
            <Text selectable style={{ color: colors.textSecondary, fontSize: 11, fontFamily: "monospace" }}>{found.url}</Text>
            <Pressable onPress={() => Linking.openURL(found.url)} style={[styles.primary, { backgroundColor: colors.primary }]}>
              <ExternalLink size={15} color="#fff" />
              <Text style={styles.primaryText}>Open in browser to download</Text>
            </Pressable>
          </>
        )}

        {found?.kind === "blueprint" && (
          <>
            <Text style={[styles.title, { color: colors.textPrimary }]}>Blueprint</Text>
            {!found.info && !found.error && <ActivityIndicator color={colors.primary} />}
            {found.error && <Text style={{ color: colors.error, fontSize: 13 }}>{found.error}</Text>}
            {found.info && (
              <>
                <Text style={{ color: colors.textPrimary, fontWeight: "700", fontSize: 15 }}>{found.info.name}</Text>
                {!!found.info.description && <Text style={[styles.body, { color: colors.textSecondary }]}>{found.info.description}</Text>}
                <Text style={[styles.body, { color: colors.textSecondary }]}>
                  {found.info.table_names.length} tables: {found.info.table_names.join(", ")} · {found.info.endpoint_count} endpoints
                </Text>
                <Pressable
                  onPress={() => importBlueprint(found.text)}
                  disabled={working}
                  style={[styles.primary, { backgroundColor: colors.primary }, working && { opacity: 0.6 }]}
                >
                  {working ? <ActivityIndicator color="#fff" size="small" /> : <CheckCircle2 size={15} color="#fff" />}
                  <Text style={styles.primaryText}>Import as a new project</Text>
                </Pressable>
              </>
            )}
          </>
        )}

        {found?.kind === "saved" && (
          <>
            <View style={styles.row}>
              <CheckCircle2 size={18} color={colors.success} />
              <Text style={[styles.title, { color: colors.textPrimary, marginBottom: 0 }]}>Received “{found.name}”</Text>
            </View>
            <Text style={[styles.body, { color: colors.textSecondary }]}>{found.fileCount} files, saved as a ZIP.</Text>
            <Pressable
              onPress={() => Sharing.shareAsync(found.uri, { mimeType: "application/zip" })}
              style={[styles.primary, { backgroundColor: colors.primary }]}
            >
              <Text style={styles.primaryText}>Save or send the ZIP</Text>
            </Pressable>
          </>
        )}

        {found?.kind === "error" && (
          <Text style={{ color: colors.error, fontSize: 13, textAlign: "center" }}>{found.message}</Text>
        )}

        {(found || progress) && (
          <Pressable onPress={reset} style={[styles.outline, { borderColor: colors.border }]}>
            <RotateCcw size={15} color={colors.textPrimary} />
            <Text style={{ color: colors.textPrimary, fontWeight: "700" }}>Scan another code</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 12 },
  frameGuide: {
    position: "absolute",
    top: "18%",
    alignSelf: "center",
    width: 240,
    height: 240,
    borderWidth: 3,
    borderColor: "rgba(255,255,255,0.8)",
    borderRadius: 20,
  },
  panel: { position: "absolute", left: 12, right: 12, bottom: 24, borderWidth: 1, borderRadius: 18, padding: 16, gap: 10 },
  title: { fontSize: 16, fontWeight: "700", textAlign: "center", marginBottom: 2 },
  body: { fontSize: 13, lineHeight: 19, textAlign: "center" },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 },
  bar: { height: 8, borderRadius: 4, overflow: "hidden" },
  barFill: { height: 8, borderRadius: 4 },
  note: { flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1, borderRadius: 10, padding: 10 },
  primary: { flexDirection: "row", gap: 8, alignItems: "center", justifyContent: "center", borderRadius: 12, paddingVertical: 13 },
  primaryText: { color: "#fff", fontWeight: "700", fontSize: 14 },
  outline: { flexDirection: "row", gap: 8, alignItems: "center", justifyContent: "center", borderWidth: 1, borderRadius: 12, paddingVertical: 12 },
});
