// ─── Share via QR ───
//
// Three options the user picks between (a whole project is far bigger
// than one QR code — see the backend's services/qr_share.py):
//   Download link  a QR of an expiring URL to the project ZIP
//   Blueprint      the design in one code, offline; rebuilt with No-AI codegen
//   QR sequence    the whole project as codes shown in turn, offline; another
//                  phone's VengaiCode scanner (Home → Scan QR) catches them
// Link/blueprint images come from the backend as PNGs; sequence frames are
// drawn here (qrTransfer.qrModules + react-native-svg) so they can animate.

import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Image, Pressable, ScrollView, Share, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";
import Svg, { Path, Rect } from "react-native-svg";
import { AlertTriangle, Download, Layers, Link2, Pause, Play, QrCode, Share2 } from "lucide-react-native";

import apiClient from "@/lib/api";
import { base64ToBytes, qrModules, qrPath } from "@/lib/qrTransfer";
import { useToast } from "@/components/ui/Toast";
import { useTheme } from "@/theme/useTheme";

const WARNING = "#eab308";

type Option = "link" | "blueprint" | "sequence";

interface QrImage {
  png_base64: string;
  version: number;
  dense: boolean;
}

interface LinkInfo {
  id: string;
  created_at: string | null;
  expires_at: string;
  revoked: boolean;
  active: boolean;
  download_count: number;
}

const OPTIONS: { id: Option; label: string; hint: string; icon: React.ElementType }[] = [
  { id: "link", label: "Download link", hint: "Any size · needs internet", icon: Link2 },
  { id: "blueprint", label: "Blueprint", hint: "One code · offline · design only", icon: QrCode },
  { id: "sequence", label: "QR sequence", hint: "Everything · offline · many codes", icon: Layers },
];

const EXPIRY = [
  { hours: 1, label: "1 hour" },
  { hours: 24, label: "1 day" },
  { hours: 168, label: "7 days" },
  { hours: 720, label: "30 days" },
];
const FRAME_SIZES = [
  { bytes: 300, label: "Easy to scan" },
  { bytes: 500, label: "Standard" },
  { bytes: 800, label: "Fewer codes" },
];
const SPEEDS = [2, 4, 6];

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

async function shareQrImage(qr: QrImage, name: string) {
  const file = new File(Paths.cache, name);
  file.create({ overwrite: true });
  file.write(base64ToBytes(qr.png_base64));
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(file.uri, { mimeType: "image/png", dialogTitle: "Save or send the QR code" });
  }
}

function fileBase(name: string): string {
  return name.trim().replace(/[^\w\s-]/g, "").replace(/\s+/g, "_").slice(0, 50) || "vengaicode_project";
}

export default function ShareScreen() {
  const { id: projectId } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const [option, setOption] = useState<Option>("link");
  const [projectName, setProjectName] = useState("");

  useEffect(() => {
    apiClient
      .get(`/projects/${projectId}`)
      .then(({ data }) => setProjectName(data?.project?.name || ""))
      .catch(() => {});
  }, [projectId]);

  return (
    <ScrollView style={{ backgroundColor: colors.background }} contentContainerStyle={styles.content}>
      <Text style={{ color: colors.textSecondary, fontSize: 13, lineHeight: 19, marginBottom: 12 }}>
        A whole project is too big for one QR code, so pick how to send it.
      </Text>
      <View style={{ gap: 8, marginBottom: 16 }}>
        {OPTIONS.map((o) => {
          const Icon = o.icon;
          const active = option === o.id;
          return (
            <Pressable
              key={o.id}
              onPress={() => setOption(o.id)}
              style={[
                styles.optionCard,
                { borderColor: active ? colors.primary : colors.border, backgroundColor: active ? colors.primaryLight : colors.surface },
              ]}
            >
              <Icon size={18} color={active ? colors.primary : colors.textTertiary} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: colors.textPrimary, fontWeight: "700", fontSize: 14 }}>{o.label}</Text>
                <Text style={{ color: colors.textSecondary, fontSize: 12 }}>{o.hint}</Text>
              </View>
            </Pressable>
          );
        })}
      </View>

      {option === "link" && <LinkOption projectId={projectId!} projectName={projectName} />}
      {option === "blueprint" && <BlueprintOption projectId={projectId!} projectName={projectName} />}
      {option === "sequence" && <SequenceOption projectId={projectId!} />}
    </ScrollView>
  );
}

// ─── shared bits ───
function Note({ children, warning }: { children: React.ReactNode; warning?: boolean }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.note, { borderColor: warning ? WARNING : colors.border, backgroundColor: colors.surface }]}>
      {warning && <AlertTriangle size={14} color={WARNING} style={{ marginTop: 2 }} />}
      <Text style={{ color: colors.textSecondary, fontSize: 12, lineHeight: 18, flex: 1 }}>{children}</Text>
    </View>
  );
}

function Chips<T extends string | number>({
  items,
  value,
  onChange,
}: {
  items: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  const { colors } = useTheme();
  return (
    <View style={styles.chipRow}>
      {items.map((item) => {
        const active = item.value === value;
        return (
          <Pressable
            key={String(item.value)}
            onPress={() => onChange(item.value)}
            style={[styles.chip, { borderColor: active ? colors.primary : colors.border, backgroundColor: active ? colors.primaryLight : "transparent" }]}
          >
            <Text style={{ color: active ? colors.primary : colors.textSecondary, fontSize: 12, fontWeight: "600" }}>{item.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function ActionButton({
  label,
  icon: Icon,
  onPress,
  loading,
  primary,
}: {
  label: string;
  icon: React.ElementType;
  onPress: () => void;
  loading?: boolean;
  primary?: boolean;
}) {
  const { colors } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      disabled={loading}
      style={[
        styles.button,
        primary ? { backgroundColor: colors.primary } : { borderWidth: 1, borderColor: colors.border },
        loading && { opacity: 0.6 },
      ]}
    >
      {loading ? (
        <ActivityIndicator size="small" color={primary ? "#fff" : colors.textPrimary} />
      ) : (
        <Icon size={15} color={primary ? "#fff" : colors.textPrimary} />
      )}
      <Text style={{ color: primary ? "#fff" : colors.textPrimary, fontWeight: "700", fontSize: 13 }}>{label}</Text>
    </Pressable>
  );
}

// ─── 1. Download link ───
function LinkOption({ projectId, projectName }: { projectId: string; projectName: string }) {
  const { colors } = useTheme();
  const { showToast } = useToast();
  const [hours, setHours] = useState(168);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<{ url: string; reach: string; qr: QrImage; link: LinkInfo } | null>(null);
  const [links, setLinks] = useState<LinkInfo[]>([]);

  const loadLinks = useCallback(async () => {
    try {
      const { data } = await apiClient.get(`/share/${projectId}/links`);
      setLinks(data.links || []);
    } catch {
      // Only a convenience list.
    }
  }, [projectId]);

  useEffect(() => {
    loadLinks();
  }, [loadLinks]);

  const create = async () => {
    setCreating(true);
    try {
      const { data } = await apiClient.post(`/share/${projectId}/links`, { expires_in_hours: hours });
      setCreated(data);
      loadLinks();
    } catch (e: any) {
      showToast(e.message || "Couldn't create the link.", "error");
    } finally {
      setCreating(false);
    }
  };

  const turnOff = async (linkId: string) => {
    try {
      await apiClient.delete(`/share/${projectId}/links/${linkId}`);
      if (created?.link.id === linkId) setCreated(null);
      showToast("Link turned off 🐯");
      loadLinks();
    } catch (e: any) {
      showToast(e.message || "Couldn't turn the link off.", "error");
    }
  };

  return (
    <View style={{ gap: 12 }}>
      <Note>
        The QR code holds a web address. Whoever scans it downloads this project's code and documents as a ZIP — no
        VengaiCode account needed — until the link expires or you turn it off.
      </Note>
      <Text style={[styles.label, { color: colors.textSecondary }]}>Link works for</Text>
      <Chips items={EXPIRY.map((e) => ({ value: e.hours, label: e.label }))} value={hours} onChange={setHours} />
      <ActionButton label={created ? "Create another link" : "Create link & QR code"} icon={QrCode} onPress={create} loading={creating} primary />

      {created && (
        <View style={[styles.result, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <Image source={{ uri: `data:image/png;base64,${created.qr.png_base64}` }} style={styles.qrImage} />
          <Text selectable style={[styles.mono, { color: colors.textPrimary }]}>{created.url}</Text>
          <Text style={{ color: colors.textSecondary, fontSize: 12 }}>Expires {when(created.link.expires_at)}</Text>
          {created.reach === "this_device" && (
            <Note warning>
              This link points at the backend's localhost address, so another device can't open it. Set PUBLIC_BASE_URL on
              the backend to its real address.
            </Note>
          )}
          {created.reach === "same_network" && (
            <Note warning>This link uses a local-network address — it only works on the same Wi-Fi/network.</Note>
          )}
          <View style={styles.row}>
            <ActionButton label="Share link" icon={Share2} onPress={() => Share.share({ message: created.url })} />
            <ActionButton
              label="Save QR image"
              icon={Download}
              onPress={() => shareQrImage(created.qr, `${fileBase(projectName)}_link_qr.png`)}
            />
          </View>
        </View>
      )}

      {links.length > 0 && (
        <View style={[styles.result, { borderColor: colors.border, backgroundColor: colors.surface, alignItems: "stretch" }]}>
          <Text style={{ color: colors.textPrimary, fontWeight: "700", fontSize: 13 }}>Links for this project</Text>
          {links.map((link) => (
            <View key={link.id} style={[styles.linkRow, { borderTopColor: colors.border }]}>
              <View style={{ flex: 1 }}>
                <Text style={{ color: link.active ? colors.success : colors.textTertiary, fontWeight: "700", fontSize: 12 }}>
                  {link.active ? "Active" : link.revoked ? "Turned off" : "Expired"}
                </Text>
                <Text style={{ color: colors.textSecondary, fontSize: 11 }}>
                  Expires {when(link.expires_at)} · {link.download_count} download{link.download_count === 1 ? "" : "s"}
                </Text>
              </View>
              {link.active && (
                <Pressable onPress={() => turnOff(link.id)} style={[styles.smallButton, { borderColor: colors.border }]}>
                  <Text style={{ color: colors.textPrimary, fontSize: 12, fontWeight: "600" }}>Turn off</Text>
                </Pressable>
              )}
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

// ─── 2. Blueprint ───
function BlueprintOption({ projectId, projectName }: { projectId: string; projectName: string }) {
  const { colors } = useTheme();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bp, setBp] = useState<{
    text: string;
    qr: QrImage;
    compressed_bytes: number;
    omitted: string[];
    table_count: number;
    endpoint_count: number;
  } | null>(null);

  const make = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.get(`/share/${projectId}/blueprint`);
      setBp(data);
    } catch (e: any) {
      setError(e.message || "Couldn't make the blueprint.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={{ gap: 12 }}>
      <Note>
        One QR code holding this project's design — tables, fields, keys, rules, API endpoints and stack — compressed. It
        works offline. The receiver imports it as a new project (Home → Scan QR, or the desktop app's Import from QR) and
        rebuilds the code with No-AI generation. AI-written code, requirements and UI designs don't travel in it.
      </Note>
      <ActionButton label={bp ? "Make it again" : "Make blueprint QR code"} icon={QrCode} onPress={make} loading={loading} primary />
      {error && <Note warning>{error}</Note>}
      {bp && (
        <View style={[styles.result, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <Image source={{ uri: `data:image/png;base64,${bp.qr.png_base64}` }} style={styles.qrImageLarge} />
          <Text style={{ color: colors.textSecondary, fontSize: 12, textAlign: "center" }}>
            {bp.table_count} table{bp.table_count === 1 ? "" : "s"}, {bp.endpoint_count} endpoint
            {bp.endpoint_count === 1 ? "" : "s"} · {bp.compressed_bytes.toLocaleString()} bytes · QR version {bp.qr.version}
          </Text>
          {bp.omitted.length > 0 && (
            <Note warning>
              To fit one code, these were left out: {bp.omitted.join("; ")}. Use a link or a QR sequence to send everything.
            </Note>
          )}
          {bp.qr.dense && <Note warning>This is a dense code — scan it at close range, or print it at least 10 cm wide.</Note>}
          <View style={styles.row}>
            <ActionButton label="Save QR image" icon={Download} onPress={() => shareQrImage(bp.qr, `${fileBase(projectName)}_blueprint_qr.png`)} />
            <ActionButton label="Share as text" icon={Share2} onPress={() => Share.share({ message: bp.text })} />
          </View>
        </View>
      )}
    </View>
  );
}

// ─── 3. QR sequence ───
function SequenceOption({ projectId }: { projectId: string }) {
  const { colors } = useTheme();
  const [frameBytes, setFrameBytes] = useState(500);
  const [fps, setFps] = useState(4);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [seq, setSeq] = useState<{
    frames: string[];
    frame_count: number;
    file_count: number;
    payload_bytes: number;
    has_code: boolean;
  } | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);

  const prepare = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.get(`/share/${projectId}/sequence`, { params: { frame_bytes: frameBytes } });
      setSeq(data);
      setIndex(0);
      setPlaying(true);
    } catch (e: any) {
      setError(e.message || "Couldn't prepare the codes.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setSeq(null);
    setPlaying(false);
  }, [frameBytes, projectId]);

  useEffect(() => {
    if (!playing || !seq) return;
    const timer = setInterval(() => setIndex((i) => (i + 1) % seq.frame_count), 1000 / fps);
    return () => clearInterval(timer);
  }, [playing, seq, fps]);

  const frame = seq?.frames[index];
  const modules = useMemo(() => (frame ? qrModules(frame) : null), [frame]);
  const border = 4;
  const size = modules ? modules.length + border * 2 : 0;

  return (
    <View style={{ gap: 12 }}>
      <Note>
        The whole project — code and documents — split across QR codes shown one after another, no internet needed. On the
        other phone open VengaiCode → Home → Scan QR and point it at this screen: the codes loop until every one is caught,
        then it saves the project as a ZIP.
      </Note>
      <Text style={[styles.label, { color: colors.textSecondary }]}>Code size</Text>
      <Chips items={FRAME_SIZES.map((s) => ({ value: s.bytes, label: s.label }))} value={frameBytes} onChange={setFrameBytes} />
      <Text style={[styles.label, { color: colors.textSecondary }]}>Speed</Text>
      <Chips items={SPEEDS.map((s) => ({ value: s, label: `${s} codes/s` }))} value={fps} onChange={setFps} />
      <ActionButton label={seq ? "Prepare again" : "Show QR sequence"} icon={Layers} onPress={prepare} loading={loading} primary />
      {error && <Note warning>{error}</Note>}

      {seq && modules && (
        <View style={[styles.result, { borderColor: colors.border, backgroundColor: colors.surface }]}>
          <Svg width={300} height={300} viewBox={`0 0 ${size} ${size}`}>
            <Rect x={0} y={0} width={size} height={size} fill="#fff" />
            <Path d={qrPath(modules)} fill="#000" transform={`translate(${border} ${border})`} />
          </Svg>
          <Text style={{ color: colors.textSecondary, fontSize: 12, textAlign: "center" }}>
            Code {index + 1} of {seq.frame_count} · {seq.file_count} files, {seq.payload_bytes.toLocaleString()} bytes compressed
          </Text>
          {!seq.has_code && <Note warning>No code has been generated yet — only the project's documents will be sent.</Note>}
          <ActionButton label={playing ? "Pause" : "Play"} icon={playing ? Pause : Play} onPress={() => setPlaying((p) => !p)} />
          <Text style={{ color: colors.textTertiary, fontSize: 11 }}>Turn the screen brightness up and keep this screen on.</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, paddingBottom: 48 },
  optionCard: { flexDirection: "row", alignItems: "center", gap: 12, borderWidth: 2, borderRadius: 14, padding: 14 },
  note: { flexDirection: "row", gap: 8, borderWidth: 1, borderRadius: 12, padding: 12 },
  label: { fontSize: 12, fontWeight: "600" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { borderWidth: 1, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6 },
  button: { flex: 1, flexDirection: "row", gap: 8, alignItems: "center", justifyContent: "center", borderRadius: 12, paddingVertical: 12, paddingHorizontal: 12 },
  result: { borderWidth: 1, borderRadius: 14, padding: 14, gap: 10, alignItems: "center" },
  qrImage: { width: 220, height: 220, backgroundColor: "#fff", borderRadius: 8 },
  qrImageLarge: { width: 280, height: 280, backgroundColor: "#fff", borderRadius: 8 },
  mono: { fontFamily: "monospace", fontSize: 11 },
  row: { flexDirection: "row", gap: 8, alignSelf: "stretch" },
  linkRow: { flexDirection: "row", alignItems: "center", gap: 8, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 8 },
  smallButton: { borderWidth: 1, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6 },
});
