// ─── Share via QR — pure helpers for the Export screen's panel ───
//
// Three ways to hand a project over with a QR code (the backend's
// services/qr_share.py explains why one code can't hold a whole project):
//   link       a QR of an expiring download URL — any size, needs the server
//   blueprint  the design in ONE code, offline; rebuilt with No-AI codegen
//   sequence   the whole project as many codes shown in turn, offline; the
//              VengaiCode mobile app scans and reassembles them
// Kept out of the components so they can be unit-tested (qrShare.test.ts).

import jsQR from "jsqr";
import QRCode from "qrcode";

export type ShareOption = "link" | "blueprint" | "sequence";

export const EXPIRY_OPTIONS: { hours: number; label: string }[] = [
  { hours: 1, label: "1 hour" },
  { hours: 24, label: "1 day" },
  { hours: 24 * 7, label: "7 days" },
  { hours: 24 * 30, label: "30 days" },
];

/** Bytes of project data per sequence code. Smaller = more codes, but
 *  each is quicker for a camera to lock onto. */
export const FRAME_SIZES: { bytes: number; label: string }[] = [
  { bytes: 300, label: "Easy to scan" },
  { bytes: 500, label: "Standard" },
  { bytes: 800, label: "Fewer codes" },
];

export const MIN_FPS = 1;
export const MAX_FPS = 8;

export type LinkReach = "anyone" | "same_network" | "this_device";

export interface QrImage {
  png_base64: string;
  version: number;
  dense: boolean;
}

export interface ShareLinkInfo {
  id: string;
  created_at: string | null;
  expires_at: string;
  revoked: boolean;
  active: boolean;
  download_count: number;
  last_downloaded_at: string | null;
}

export interface CreatedLink {
  url: string;
  reach: LinkReach;
  qr: QrImage;
  link: ShareLinkInfo;
}

export interface BlueprintInfo {
  text: string;
  qr: QrImage;
  compressed_bytes: number;
  omitted: string[];
  table_count: number;
  endpoint_count: number;
}

export interface SequenceInfo {
  sid: string;
  frames: string[];
  frame_count: number;
  payload_bytes: number;
  file_count: number;
  name: string;
  has_code: boolean;
}

/** What a link's audience is, in words — null when anyone can open it. */
export function reachWarning(reach: LinkReach): string | null {
  if (reach === "this_device") {
    return "This link points at this computer (localhost), so another device can't open it. Set PUBLIC_BASE_URL on the backend to its real address.";
  }
  if (reach === "same_network") {
    return "This link uses a local-network address — it only works for devices on the same Wi-Fi/network.";
  }
  return null;
}

export function pngDataUrl(qr: QrImage): string {
  return `data:image/png;base64,${qr.png_base64}`;
}

export function qrFileName(projectName: string, kind: ShareOption): string {
  const base = projectName.trim().replace(/[^\w\s-]/g, "").replace(/\s+/g, "_").slice(0, 50) || "vengaicode_project";
  return `${base}_${kind}_qr.png`;
}

/** How long one pass through a sequence takes, as text ("about 8 s"). */
export function loopDuration(frameCount: number, fps: number): string {
  const seconds = Math.max(1, Math.round(frameCount / fps));
  return seconds < 60 ? `about ${seconds} s` : `about ${Math.round(seconds / 6) / 10} min`;
}

export function clampFps(fps: number): number {
  return Math.min(MAX_FPS, Math.max(MIN_FPS, Math.round(fps)));
}

export function formatWhen(iso: string | null): string {
  if (!iso) return "";
  const when = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(when.getTime()) ? iso : when.toLocaleString();
}

/** Draws a code on a canvas (the sequence player's frames). */
export async function drawQr(canvas: HTMLCanvasElement, text: string, width: number): Promise<void> {
  await QRCode.toCanvas(canvas, text, { errorCorrectionLevel: "M", margin: 4, width });
}

/** The text of the QR code in an image's pixels, or null if none is
 *  readable — used to import a blueprint from a saved/received picture. */
export function decodeQrPixels(data: Uint8ClampedArray, width: number, height: number): string | null {
  const found = jsQR(data, width, height, { inversionAttempts: "attemptBoth" });
  return found ? found.data : null;
}

/** A picked image file's QR text (browser only). */
export async function decodeQrFile(file: Blob): Promise<string | null> {
  const bitmap = await createImageBitmap(file);
  // Big photos are shrunk: jsQR is fast on ~1000px and a QR code needs far less.
  const scale = Math.min(1, 1200 / Math.max(bitmap.width, bitmap.height));
  const width = Math.max(1, Math.round(bitmap.width * scale));
  const height = Math.max(1, Math.round(bitmap.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.drawImage(bitmap, 0, 0, width, height);
  const pixels = ctx.getImageData(0, 0, width, height);
  return decodeQrPixels(pixels.data, width, height);
}

/** Which kind of code a text is — the same rule the mobile scanner uses. */
export function classifyQrText(text: string): "link" | "blueprint" | "sequence" | "unknown" {
  const t = text.trim();
  if (/^https?:\/\//i.test(t)) return "link";
  if (t.toUpperCase().startsWith("VGC1:")) return "blueprint";
  if (t.startsWith("VGS1:")) return "sequence";
  return "unknown";
}
