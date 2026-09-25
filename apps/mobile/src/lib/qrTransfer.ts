// ─── Share via QR — the formats, on the phone ───
//
// The backend (services/qr_share.py) makes three kinds of QR code, and
// this app can both SHOW them and SCAN them:
//   link       an https URL to a project ZIP — opened in the browser
//   blueprint  "VGC1:" + base45(deflate(JSON)) — the design in one code;
//              the backend decodes it on import, so the phone never has to
//   sequence   "VGS1:<SID>:<index>:<count>:<base45 chunk>" frames, shown
//              one after another; together they are the whole project
//              (code + documents), compressed. Only this app reassembles
//              them — that's what the helpers below are for.
// SID is the CRC32 of the whole compressed payload (hex): it checks the
// reassembled bytes, and with <count> tells two transfers apart.
// Pure functions + one small class, so all of it is unit-tested
// (qrTransfer.test.ts) against frames the real backend produced.

import { inflateSync, strFromU8, strToU8, zipSync } from "fflate";
import QRCode from "qrcode";

export const BLUEPRINT_PREFIX = "VGC1:";
export const SEQUENCE_PREFIX = "VGS1";
const BASE45 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:";
const BASE45_INDEX: Record<string, number> = Object.fromEntries([...BASE45].map((ch, i) => [ch, i]));

export type ScanKind = "link" | "blueprint" | "sequence" | "unknown";

export function classifyScan(text: string): ScanKind {
  const t = text.trim();
  if (/^https?:\/\//i.test(t)) return "link";
  if (t.toUpperCase().startsWith(BLUEPRINT_PREFIX)) return "blueprint";
  if (t.startsWith(`${SEQUENCE_PREFIX}:`)) return "sequence";
  return "unknown";
}

/** RFC 9285. Throws on text that isn't base45. */
export function base45Decode(text: string): Uint8Array {
  const out: number[] = [];
  for (let i = 0; i < text.length; i += 3) {
    const group = [...text.slice(i, i + 3)].map((ch) => {
      const v = BASE45_INDEX[ch];
      if (v === undefined) throw new Error("not base45");
      return v;
    });
    if (group.length === 3) {
      const n = group[0] + group[1] * 45 + group[2] * 2025;
      if (n > 0xffff) throw new Error("invalid base45 group");
      out.push(n >> 8, n & 0xff);
    } else if (group.length === 2) {
      const n = group[0] + group[1] * 45;
      if (n > 0xff) throw new Error("invalid base45 group");
      out.push(n);
    } else {
      throw new Error("truncated base45");
    }
  }
  return Uint8Array.from(out);
}

let crcTable: Uint32Array | null = null;

/** Standard CRC-32 (the same number as Python's zlib.crc32). */
export function crc32(bytes: Uint8Array): number {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      crcTable[n] = c >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (const b of bytes) crc = crcTable[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

export interface Frame {
  sid: string;
  index: number;
  count: number;
  data: Uint8Array;
}

/** One sequence frame, or null for anything that isn't a valid one. */
export function parseFrame(text: string): Frame | null {
  const parts = text.split(":");
  if (parts.length < 5 || parts[0] !== SEQUENCE_PREFIX) return null;
  const [, sid, indexText, countText] = parts;
  // The data may itself contain ":" (it's in the base45 alphabet).
  const data = parts.slice(4).join(":");
  const index = Number(indexText);
  const count = Number(countText);
  if (!/^[0-9A-F]{8}$/.test(sid) || !Number.isInteger(index) || !Number.isInteger(count)) return null;
  if (count < 1 || index < 0 || index >= count) return null;
  try {
    return { sid, index, count, data: base45Decode(data) };
  } catch {
    return null;
  }
}

export interface AddResult {
  /** The frame belongs to the transfer being collected (new or repeat). */
  accepted: boolean;
  /** It was a frame this collector hadn't seen yet. */
  isNew: boolean;
  /** A valid frame of a DIFFERENT transfer — offer to start over. */
  otherTransfer: boolean;
}

/** Collects scanned frames in any order; repeats are harmless. The first
 *  frame fixes which transfer is being received. */
export class SequenceCollector {
  private key: string | null = null;
  private parts = new Map<number, Uint8Array>();
  sid = "";
  count = 0;

  add(text: string): AddResult {
    const frame = parseFrame(text);
    if (!frame) return { accepted: false, isNew: false, otherTransfer: false };
    const key = `${frame.sid}:${frame.count}`;
    if (this.key === null) {
      this.key = key;
      this.sid = frame.sid;
      this.count = frame.count;
    } else if (key !== this.key) {
      return { accepted: false, isNew: false, otherTransfer: true };
    }
    const isNew = !this.parts.has(frame.index);
    if (isNew) this.parts.set(frame.index, frame.data);
    return { accepted: true, isNew, otherTransfer: false };
  }

  get received(): number {
    return this.parts.size;
  }

  get complete(): boolean {
    return this.count > 0 && this.parts.size === this.count;
  }

  missing(): number[] {
    const out: number[] = [];
    for (let i = 0; i < this.count; i++) if (!this.parts.has(i)) out.push(i);
    return out;
  }

  /** The reassembled payload, checked against the SID. Throws if it's
   *  incomplete or doesn't check out. */
  assemble(): Uint8Array {
    if (!this.complete) throw new Error(`Still missing ${this.count - this.received} of ${this.count} codes.`);
    const total = [...this.parts.values()].reduce((n, p) => n + p.length, 0);
    const payload = new Uint8Array(total);
    let offset = 0;
    for (let i = 0; i < this.count; i++) {
      const part = this.parts.get(i)!;
      payload.set(part, offset);
      offset += part.length;
    }
    const check = crc32(payload).toString(16).toUpperCase().padStart(8, "0");
    if (check !== this.sid) throw new Error("The scanned data didn't check out — scan the sequence again.");
    return payload;
  }
}

export interface Bundle {
  name: string;
  files: [string, string][];
}

/** The project inside a reassembled payload. */
export function decodeBundle(payload: Uint8Array): Bundle {
  const doc = JSON.parse(strFromU8(inflateSync(payload)));
  if (!doc || doc.v !== 1 || !Array.isArray(doc.files)) {
    throw new Error("This sequence was made by a newer VengaiCode — update the app to receive it.");
  }
  const files = doc.files.filter(
    (f: unknown): f is [string, string] => Array.isArray(f) && typeof f[0] === "string" && typeof f[1] === "string"
  );
  return { name: typeof doc.name === "string" && doc.name.trim() ? doc.name : "VengaiCode project", files };
}

/** A relative path with no way out of the folder it's unzipped into —
 *  the same rule as the backend's export (_safe_zip_path): empty, "." and
 *  ".." segments are dropped, so nothing can be absolute or climb up. */
export function safeZipPath(path: string): string {
  return path
    .split(/[\\/]+/)
    .filter((part) => part && part !== "." && part !== "..")
    .join("/");
}

/** The ZIP "Download ZIP" would have given — same paths, same contents. */
export function buildZip(files: [string, string][]): Uint8Array {
  const entries: Record<string, Uint8Array> = {};
  for (const [path, content] of files) {
    const safe = safeZipPath(path);
    if (safe) entries[safe] = strToU8(content);
  }
  return zipSync(entries, { level: 6 });
}

export function zipFileName(name: string): string {
  const base = name.trim().replace(/[^\w\s-]/g, "").replace(/\s+/g, "_").slice(0, 60);
  return `${base || "vengaicode_project"}.zip`;
}

/** A QR code's dark/light modules for drawing (row-major, true = dark). */
export function qrModules(text: string, errorCorrectionLevel: "L" | "M" | "Q" | "H" = "M"): boolean[][] {
  const qr = QRCode.create(text, { errorCorrectionLevel });
  const { size, data } = qr.modules;
  const rows: boolean[][] = [];
  for (let r = 0; r < size; r++) {
    const row: boolean[] = [];
    for (let c = 0; c < size; c++) row.push(Boolean(data[r * size + c]));
    rows.push(row);
  }
  return rows;
}

/** One SVG path ("M x y h1 v1 h-1 z" per dark module) for a QR matrix,
 *  in module units — cheap to render and to scale. */
export function qrPath(modules: boolean[][]): string {
  const parts: string[] = [];
  modules.forEach((row, y) => {
    row.forEach((dark, x) => {
      if (dark) parts.push(`M${x} ${y}h1v1h-1z`);
    });
  });
  return parts.join("");
}

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/** Base64 (e.g. the backend's QR PNG) to bytes, without Buffer/atob. */
export function base64ToBytes(b64: string): Uint8Array {
  const clean = b64.replace(/[^A-Za-z0-9+/]/g, "");
  const out = new Uint8Array(Math.floor((clean.length * 3) / 4));
  let o = 0;
  for (let i = 0; i < clean.length; i += 4) {
    const n =
      (B64.indexOf(clean[i]) << 18) |
      (B64.indexOf(clean[i + 1]) << 12) |
      ((B64.indexOf(clean[i + 2] ?? "A") & 63) << 6) |
      (B64.indexOf(clean[i + 3] ?? "A") & 63);
    out[o++] = (n >> 16) & 0xff;
    if (i + 2 < clean.length) out[o++] = (n >> 8) & 0xff;
    if (i + 3 < clean.length) out[o++] = n & 0xff;
  }
  return out.subarray(0, o);
}
