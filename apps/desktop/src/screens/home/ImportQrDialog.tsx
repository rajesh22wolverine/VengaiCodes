// ─── Import from QR — the Dashboard's receiving side ───
//
// A blueprint QR code (Export → Share via QR → Blueprint) becomes a new
// project here: pick a picture of the code (decoded in the browser with
// jsQR) or paste its text, check what's in it, import. The backend does
// the decoding and validation (POST /share/blueprint/inspect + /import).
// A download-link code just needs a browser, and a QR sequence needs a
// camera — both are recognized and explained instead of failing.

import { useRef, useState } from "react";
import { useDispatch } from "react-redux";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Copy, Loader2, QrCode, Upload, X } from "lucide-react";
import toast from "react-hot-toast";

import apiClient from "@/lib/api";
import { AppDispatch } from "@/store";
import { fetchProjects } from "@/store/slices/projectSlice";
import { classifyQrText, decodeQrFile } from "../export/qrShare";

interface Inspected {
  name: string;
  description: string;
  stack: Record<string, string>;
  table_names: string[];
  endpoint_count: number;
}

export default function ImportQrDialog({ onClose }: { onClose: () => void }) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const fileInput = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [reading, setReading] = useState(false);
  const [checking, setChecking] = useState(false);
  const [importing, setImporting] = useState(false);
  const [inspected, setInspected] = useState<Inspected | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const kind = text.trim() ? classifyQrText(text) : null;

  const check = async (value: string) => {
    setInspected(null);
    setProblem(null);
    const k = classifyQrText(value);
    if (k !== "blueprint") return; // explained in the panel below
    setChecking(true);
    try {
      const { data } = await apiClient.post("/share/blueprint/inspect", { text: value.trim() });
      setInspected(data);
    } catch (e: any) {
      setProblem(e.message || "That code couldn't be read.");
    } finally {
      setChecking(false);
    }
  };

  const onPickImage = async (file: File | undefined) => {
    if (!file) return;
    setReading(true);
    setProblem(null);
    try {
      const found = await decodeQrFile(file);
      if (!found) {
        setText("");
        setInspected(null);
        setProblem("No QR code was found in that picture — try a sharper, straighter photo or the saved QR image.");
        return;
      }
      setText(found);
      await check(found);
    } catch {
      setProblem("That file couldn't be opened as a picture.");
    } finally {
      setReading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const doImport = async () => {
    setImporting(true);
    try {
      const { data } = await apiClient.post("/share/blueprint/import", { text: text.trim() });
      toast.success(`Imported “${data.name}” 🐯`);
      if (data.notes?.length) toast(data.notes.join("\n"), { duration: 8000 });
      dispatch(fetchProjects());
      onClose();
      navigate(`/project/${data.project_id}/architecture`);
    } catch (e: any) {
      setProblem(e.message || "Couldn't import the blueprint.");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-5 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <QrCode className="w-5 h-5 text-[var(--color-primary)]" />
          <h2 className="flex-1 text-base font-semibold text-[var(--color-text-primary)]">Import from a QR code</h2>
          <button onClick={onClose} aria-label="Close" className="text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-xs text-[var(--color-text-secondary)]">
          Turn someone's <strong>blueprint</strong> QR code into a new project here. You can then rebuild its code
          instantly with No-AI generation.
        </p>

        <input ref={fileInput} type="file" accept="image/*" className="hidden" onChange={(e) => onPickImage(e.target.files?.[0])} />
        <button
          onClick={() => fileInput.current?.click()}
          disabled={reading}
          className="w-full py-2.5 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] text-sm font-semibold text-[var(--color-text-primary)] flex items-center justify-center gap-2 hover:bg-[var(--color-background)] disabled:opacity-60"
        >
          {reading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
          Choose a picture of the QR code
        </button>

        <label className="block text-xs text-[var(--color-text-secondary)]">
          <span className="block mb-1 font-medium">…or paste the code's text</span>
          <textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setInspected(null);
              setProblem(null);
            }}
            onBlur={() => text.trim() && !inspected && check(text)}
            rows={3}
            placeholder="VGC1:…"
            className="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-xs font-mono text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
          />
        </label>

        {kind === "link" && (
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] p-3 text-xs text-[var(--color-text-secondary)] space-y-2">
            <p>That's a <strong>download link</strong> — open it in a web browser to download the project's ZIP.</p>
            <button
              onClick={() => navigator.clipboard.writeText(text.trim()).then(() => toast.success("Link copied"))}
              className="px-3 py-1.5 rounded-lg border border-[var(--color-border)] text-xs font-semibold flex items-center gap-1.5"
            >
              <Copy className="w-3.5 h-3.5" /> Copy link
            </button>
          </div>
        )}
        {kind === "sequence" && (
          <p className="rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] p-3 text-xs text-[var(--color-text-secondary)]">
            That's one code of a <strong>QR sequence</strong>. Sequences are received with the VengaiCode mobile app's
            scanner, which catches every code as they play.
          </p>
        )}
        {kind === "unknown" && (
          <p className="text-xs text-[var(--color-text-secondary)]">That isn't a VengaiCode code.</p>
        )}

        {checking && (
          <p className="text-xs text-[var(--color-text-secondary)] flex items-center gap-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin" /> Reading the blueprint…
          </p>
        )}
        {problem && (
          <div className="flex gap-2 rounded-xl border border-[var(--color-warning)] bg-[var(--color-warning-light)] p-3 text-xs text-[var(--color-text-primary)]">
            <AlertTriangle className="w-4 h-4 flex-shrink-0 text-[var(--color-warning)]" />
            <span>{problem}</span>
          </div>
        )}

        {inspected && (
          <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] p-3 text-xs text-[var(--color-text-secondary)] space-y-1">
            <p className="text-sm font-semibold text-[var(--color-text-primary)]">{inspected.name}</p>
            {inspected.description && <p>{inspected.description}</p>}
            {inspected.stack.frontend_framework && (
              <p>
                Stack: {inspected.stack.frontend_framework} + {inspected.stack.backend_framework || "no backend"}
                {inspected.stack.api_style ? ` (${inspected.stack.api_style})` : ""}
              </p>
            )}
            <p>
              {inspected.table_names.length} table{inspected.table_names.length === 1 ? "" : "s"}:{" "}
              {inspected.table_names.join(", ")} · {inspected.endpoint_count} endpoint
              {inspected.endpoint_count === 1 ? "" : "s"}
            </p>
          </div>
        )}

        <button
          onClick={doImport}
          disabled={!inspected || importing}
          className="w-full py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {importing && <Loader2 className="w-4 h-4 animate-spin" />}
          Import as a new project
        </button>
      </div>
    </div>
  );
}
