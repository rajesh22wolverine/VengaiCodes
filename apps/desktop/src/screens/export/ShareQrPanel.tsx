// ─── Share via QR — the Export screen's panel ───
//
// Three options the user picks between (see qrShare.ts / the backend's
// services/qr_share.py for why a single QR code can't hold a project):
//   Download link  — a QR of an expiring URL to the ZIP (needs the server)
//   Blueprint      — the design in one code, offline; rebuilt with No-AI codegen
//   QR sequence    — the whole project as codes shown in turn, offline; the
//                    VengaiCode mobile app scans and reassembles them

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  AlertTriangle, CheckCircle2, Copy, Download, Layers, Link2, Loader2,
  Pause, Play, QrCode, Smartphone,
} from "lucide-react";
import toast from "react-hot-toast";

import apiClient from "@/lib/api";
import {
  BlueprintInfo, CreatedLink, EXPIRY_OPTIONS, FRAME_SIZES, MAX_FPS, MIN_FPS, QrImage,
  SequenceInfo, ShareLinkInfo, ShareOption, clampFps, drawQr, formatWhen, loopDuration,
  pngDataUrl, qrFileName, reachWarning,
} from "./qrShare";

interface Props {
  projectId: string;
  projectName: string;
}

const OPTIONS: { id: ShareOption; label: string; hint: string; icon: React.ElementType }[] = [
  { id: "link", label: "Download link", hint: "Any size · needs internet", icon: Link2 },
  { id: "blueprint", label: "Blueprint", hint: "One code · offline · design only", icon: QrCode },
  { id: "sequence", label: "QR sequence", hint: "Everything · offline · many codes", icon: Layers },
];

const BUTTON_PRIMARY =
  "px-4 py-2.5 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center justify-center gap-2";
const BUTTON_SECONDARY =
  "px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] text-[var(--color-text-primary)] text-xs font-semibold hover:bg-[var(--color-surface)] transition-colors flex items-center justify-center gap-1.5 disabled:opacity-60";

function saveQrImage(qr: QrImage, filename: string) {
  const bytes = Uint8Array.from(atob(qr.png_base64), (c) => c.charCodeAt(0));
  const url = window.URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
  const link = document.createElement("a");
  link.href = url;
  link.setAttribute("download", filename);
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

async function copyText(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} copied`);
  } catch {
    toast.error("Couldn't copy — select the text and copy it by hand.");
  }
}

function Note({ tone = "info", children }: { tone?: "info" | "warning"; children: React.ReactNode }) {
  const warning = tone === "warning";
  return (
    <div
      className={`flex gap-2 rounded-xl border p-3 text-xs leading-relaxed ${
        warning
          ? "border-[var(--color-warning)] bg-[var(--color-warning-light)] text-[var(--color-text-primary)]"
          : "border-[var(--color-border)] bg-[var(--color-background)] text-[var(--color-text-secondary)]"
      }`}
    >
      {warning && <AlertTriangle className="w-4 h-4 flex-shrink-0 text-[var(--color-warning)]" />}
      <div>{children}</div>
    </div>
  );
}

// ═══════════════════════════════════════════════
//  1. Download link
// ═══════════════════════════════════════════════
function LinkOption({ projectId, projectName }: Props) {
  const [hours, setHours] = useState(24 * 7);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<CreatedLink | null>(null);
  const [links, setLinks] = useState<ShareLinkInfo[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const loadLinks = useCallback(async () => {
    try {
      const { data } = await apiClient.get(`/share/${projectId}/links`);
      setLinks(data.links || []);
    } catch {
      // The list is a convenience; creating a link still works without it.
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
    } catch (error: any) {
      toast.error(error.message || "Couldn't create the link.");
    } finally {
      setCreating(false);
    }
  };

  const turnOff = async (linkId: string) => {
    setBusyId(linkId);
    try {
      await apiClient.delete(`/share/${projectId}/links/${linkId}`);
      if (created?.link.id === linkId) setCreated(null);
      toast.success("Link turned off — it no longer downloads anything.");
      loadLinks();
    } catch (error: any) {
      toast.error(error.message || "Couldn't turn the link off.");
    } finally {
      setBusyId(null);
    }
  };

  const warning = created ? reachWarning(created.reach) : null;

  return (
    <div className="space-y-4">
      <Note>
        The QR code holds a web address. Whoever scans it downloads this project's code and
        documents as a ZIP — no VengaiCode account needed — until the link expires or you turn it off.
      </Note>

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-[var(--color-text-secondary)]">
          <span className="block mb-1 font-medium">Link works for</span>
          <select
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-sm text-[var(--color-text-primary)]"
          >
            {EXPIRY_OPTIONS.map((o) => (
              <option key={o.hours} value={o.hours}>{o.label}</option>
            ))}
          </select>
        </label>
        <button onClick={create} disabled={creating} className={BUTTON_PRIMARY}>
          {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <QrCode className="w-4 h-4" />}
          {created ? "Create another link" : "Create link & QR code"}
        </button>
      </div>

      {created && (
        <div className="flex flex-col sm:flex-row gap-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] p-4">
          <img src={pngDataUrl(created.qr)} alt="Download link QR code" className="w-48 h-48 rounded-lg bg-white self-center" />
          <div className="flex-1 min-w-0 space-y-3">
            <div>
              <p className="text-xs font-medium text-[var(--color-text-secondary)] mb-1">Link</p>
              <input
                readOnly
                value={created.url}
                onFocus={(e) => e.target.select()}
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs font-mono text-[var(--color-text-primary)]"
              />
            </div>
            <p className="text-xs text-[var(--color-text-secondary)]">Expires {formatWhen(created.link.expires_at)}</p>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => copyText(created.url, "Link")} className={BUTTON_SECONDARY}>
                <Copy className="w-3.5 h-3.5" /> Copy link
              </button>
              <button onClick={() => saveQrImage(created.qr, qrFileName(projectName, "link"))} className={BUTTON_SECONDARY}>
                <Download className="w-3.5 h-3.5" /> Save QR image
              </button>
            </div>
            {warning && <Note tone="warning">{warning}</Note>}
          </div>
        </div>
      )}

      {links.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-[var(--color-text-primary)] mb-2">Links for this project</p>
          <div className="divide-y divide-[var(--color-border)] rounded-xl border border-[var(--color-border)]">
            {links.map((link) => (
              <div key={link.id} className="flex items-center gap-3 px-3 py-2 text-xs">
                <span
                  className={`font-semibold ${
                    link.active ? "text-[var(--color-success)]" : "text-[var(--color-text-tertiary)]"
                  }`}
                >
                  {link.active ? "Active" : link.revoked ? "Turned off" : "Expired"}
                </span>
                <span className="flex-1 text-[var(--color-text-secondary)] truncate">
                  Made {formatWhen(link.created_at)} · expires {formatWhen(link.expires_at)} ·{" "}
                  {link.download_count} download{link.download_count === 1 ? "" : "s"}
                </span>
                {link.active && (
                  <button onClick={() => turnOff(link.id)} disabled={busyId === link.id} className={BUTTON_SECONDARY}>
                    {busyId === link.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : "Turn off"}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════
//  2. Blueprint
// ═══════════════════════════════════════════════
function BlueprintOption({ projectId, projectName }: Props) {
  const [loading, setLoading] = useState(false);
  const [blueprint, setBlueprint] = useState<BlueprintInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  const make = async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await apiClient.get(`/share/${projectId}/blueprint`);
      setBlueprint(data);
    } catch (e: any) {
      setError(e.message || "Couldn't make the blueprint.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <Note>
        One QR code holding this project's <strong>design</strong> — its tables, fields, keys, rules, API
        endpoints and chosen stack — compressed. It works offline. The receiver imports it as a new project
        (VengaiCode → Dashboard → Import from QR, or the mobile app's scanner) and rebuilds the code with
        <strong> No-AI generation</strong>. AI-written code, requirements and UI designs don't travel in it.
      </Note>
      <button onClick={make} disabled={loading} className={BUTTON_PRIMARY}>
        {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <QrCode className="w-4 h-4" />}
        {blueprint ? "Make it again" : "Make blueprint QR code"}
      </button>
      {error && <Note tone="warning">{error}</Note>}

      {blueprint && (
        <div className="flex flex-col sm:flex-row gap-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] p-4">
          <img src={pngDataUrl(blueprint.qr)} alt="Blueprint QR code" className="w-64 h-64 rounded-lg bg-white self-center" />
          <div className="flex-1 min-w-0 space-y-3 text-xs text-[var(--color-text-secondary)]">
            <p>
              <CheckCircle2 className="inline w-3.5 h-3.5 mr-1 text-[var(--color-success)]" />
              {blueprint.table_count} table{blueprint.table_count === 1 ? "" : "s"} and {blueprint.endpoint_count} endpoint
              {blueprint.endpoint_count === 1 ? "" : "s"} in {blueprint.compressed_bytes.toLocaleString()} bytes
              (QR version {blueprint.qr.version}).
            </p>
            {blueprint.omitted.length > 0 && (
              <Note tone="warning">
                To fit one code, these were left out: {blueprint.omitted.join("; ")}. Use a download link or a
                QR sequence to send everything.
              </Note>
            )}
            {blueprint.qr.dense && (
              <Note tone="warning">
                This is a dense code — scan it from the screen at close range, or print it at least 10 cm wide.
              </Note>
            )}
            <div className="flex flex-wrap gap-2">
              <button onClick={() => saveQrImage(blueprint.qr, qrFileName(projectName, "blueprint"))} className={BUTTON_SECONDARY}>
                <Download className="w-3.5 h-3.5" /> Save QR image
              </button>
              <button onClick={() => copyText(blueprint.text, "Blueprint text")} className={BUTTON_SECONDARY}>
                <Copy className="w-3.5 h-3.5" /> Copy as text
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════
//  3. QR sequence
// ═══════════════════════════════════════════════
function SequenceOption({ projectId }: Props) {
  const [frameBytes, setFrameBytes] = useState(500);
  const [fps, setFps] = useState(4);
  const [loading, setLoading] = useState(false);
  const [sequence, setSequence] = useState<SequenceInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [index, setIndex] = useState(0);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const prepare = async () => {
    setLoading(true);
    setError(null);
    setPlaying(false);
    try {
      const { data } = await apiClient.get(`/share/${projectId}/sequence`, { params: { frame_bytes: frameBytes } });
      setSequence(data);
      setIndex(0);
      setPlaying(true);
    } catch (e: any) {
      setError(e.message || "Couldn't prepare the codes.");
    } finally {
      setLoading(false);
    }
  };

  // A different frame size is a different set of codes.
  useEffect(() => {
    setSequence(null);
    setPlaying(false);
  }, [frameBytes, projectId]);

  useEffect(() => {
    if (!playing || !sequence) return;
    const timer = window.setInterval(() => setIndex((i) => (i + 1) % sequence.frame_count), 1000 / fps);
    return () => window.clearInterval(timer);
  }, [playing, sequence, fps]);

  useEffect(() => {
    const frame = sequence?.frames[index];
    if (frame && canvasRef.current) {
      drawQr(canvasRef.current, frame, 360).catch(() => setError("Couldn't draw the code."));
    }
  }, [sequence, index]);

  return (
    <div className="space-y-4">
      <Note>
        The whole project — code and documents — split across a series of QR codes shown one after
        another, with no internet needed. On the other phone open the <strong>VengaiCode mobile app → Scan QR</strong>{" "}
        and point it at this screen: the codes loop until every one is caught, then it saves the project as a ZIP.
      </Note>

      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-[var(--color-text-secondary)]">
          <span className="block mb-1 font-medium">Code size</span>
          <select
            value={frameBytes}
            onChange={(e) => setFrameBytes(Number(e.target.value))}
            className="rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-sm text-[var(--color-text-primary)]"
          >
            {FRAME_SIZES.map((s) => (
              <option key={s.bytes} value={s.bytes}>{s.label}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-[var(--color-text-secondary)]">
          <span className="block mb-1 font-medium">Speed: {fps} codes/second</span>
          <input
            type="range"
            min={MIN_FPS}
            max={MAX_FPS}
            value={fps}
            onChange={(e) => setFps(clampFps(Number(e.target.value)))}
            className="w-40"
          />
        </label>
        <button onClick={prepare} disabled={loading} className={BUTTON_PRIMARY}>
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Layers className="w-4 h-4" />}
          {sequence ? "Prepare again" : "Show QR sequence"}
        </button>
      </div>
      {error && <Note tone="warning">{error}</Note>}

      {sequence && (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] p-4">
          <canvas ref={canvasRef} className="rounded-lg bg-white" style={{ width: 360, height: 360 }} />
          <div className="flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
            <button onClick={() => setPlaying((p) => !p)} className={BUTTON_SECONDARY}>
              {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
              {playing ? "Pause" : "Play"}
            </button>
            <span>
              Code {index + 1} of {sequence.frame_count} · {sequence.file_count} files,{" "}
              {sequence.payload_bytes.toLocaleString()} bytes compressed · one loop takes{" "}
              {loopDuration(sequence.frame_count, fps)}
            </span>
          </div>
          {!sequence.has_code && (
            <Note tone="warning">No code has been generated yet — only this project's documents will be sent.</Note>
          )}
          <p className="text-xs text-[var(--color-text-tertiary)] flex items-center gap-1">
            <Smartphone className="w-3.5 h-3.5" /> Hold the phone steady, 20–40 cm from the screen.
          </p>
        </div>
      )}
    </div>
  );
}

export default function ShareQrPanel({ projectId, projectName }: Props) {
  const [option, setOption] = useState<ShareOption>("link");

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.22 }}
      className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 mb-6"
    >
      <div className="flex items-center gap-2 mb-1">
        <QrCode className="w-4 h-4 text-[var(--color-primary)]" />
        <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">Share via QR code</h3>
      </div>
      <p className="text-xs text-[var(--color-text-secondary)] mb-4">
        A whole project is too big for one QR code, so pick how to send it.
      </p>

      <div className="grid gap-2 sm:grid-cols-3 mb-5">
        {OPTIONS.map((o) => {
          const Icon = o.icon;
          const active = option === o.id;
          return (
            <button
              key={o.id}
              onClick={() => setOption(o.id)}
              className={`rounded-xl border p-3 text-left transition-colors ${
                active
                  ? "border-[var(--color-primary)] bg-[var(--color-primary-light)]"
                  : "border-[var(--color-border)] bg-[var(--color-background)] hover:bg-[var(--color-surface-raised)]"
              }`}
            >
              <span className="flex items-center gap-2 text-sm font-semibold text-[var(--color-text-primary)]">
                <Icon className={`w-4 h-4 ${active ? "text-[var(--color-primary)]" : "text-[var(--color-text-tertiary)]"}`} />
                {o.label}
              </span>
              <span className="block mt-1 text-xs text-[var(--color-text-secondary)]">{o.hint}</span>
            </button>
          );
        })}
      </div>

      {option === "link" && <LinkOption projectId={projectId} projectName={projectName} />}
      {option === "blueprint" && <BlueprintOption projectId={projectId} projectName={projectName} />}
      {option === "sequence" && <SequenceOption projectId={projectId} projectName={projectName} />}
    </motion.div>
  );
}
