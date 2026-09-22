import { useState } from "react";
import { Loader2, ScanSearch, Wand2, AlertTriangle, Check, X } from "lucide-react";
import toast from "react-hot-toast";

import apiClient from "@/lib/api";

/**
 * UI for the deterministic page engine (backend: /api/v1/page/*).
 *
 * Nothing here calls an AI model. Analysis is a real parse of the page,
 * and a change request is matched against an explicit rule table — so
 * anything it doesn't understand comes back as a refusal listing what it
 * *does* understand, instead of a model guessing at an edit. That's why
 * the "couldn't do this" state below is shown as prominently as success.
 */

interface PageIssue {
  type: string;
  index: number | null;
  message: string;
}

interface PageSummary {
  element_count: number;
  by_tag: Record<string, number>;
  ids: string[];
  classes: string[];
  headings: { index: number; level: number; text: string }[];
  images: { index: number; src: string | null; alt: string | null }[];
  links: { index: number; href: string | null; text: string }[];
  forms: { index: number; action: string | null; method: string; fields: { name: string | null; type: string | null }[] }[];
  buttons: { index: number; text: string | null }[];
  inputs: { index: number; name: string | null; type: string | null }[];
  colors_used: string[];
  fonts_used: string[];
  word_count: number;
  stylesheet: { rule_count: number; selectors: string[] };
}

interface AnalyzeResponse {
  summary: PageSummary;
  issues: PageIssue[];
}

interface UnderstoodCommand {
  explanation: string;
  edits: Record<string, unknown>[];
}

interface NotUnderstoodCommand {
  error: string;
  suggestions: string[];
}

interface CommandResponse {
  understood: UnderstoodCommand[];
  not_understood: NotUnderstoodCommand[];
  supported_phrasings: string[];
  preview?: { html: string; css: string; html_changed: boolean; css_changed: boolean };
  applied: boolean;
  html?: string;
  css?: string;
}

export default function PageInspector({
  html,
  css,
  onApply,
}: {
  html: string;
  css: string;
  onApply: (html: string, css: string) => void;
}) {
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [command, setCommand] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<CommandResponse | null>(null);

  const analyze = async () => {
    if (!html.trim()) {
      toast.error("This page has no HTML to analyze yet.");
      return;
    }
    setIsAnalyzing(true);
    try {
      const { data } = await apiClient.post("/page/analyze", { html, css });
      setAnalysis({ summary: data.summary, issues: data.issues });
    } catch (error: any) {
      toast.error(error.message || "Couldn't analyze this page.");
    } finally {
      setIsAnalyzing(false);
    }
  };

  const runCommand = async (apply: boolean) => {
    if (!command.trim()) return;
    setIsRunning(true);
    try {
      const { data } = await apiClient.post("/page/command", { html, css, command, apply });
      setResult(data);
      if (apply && data.applied) {
        onApply(data.html, data.css);
        setCommand("");
        toast.success("Change applied 🐯");
        // The page changed underneath it, so the old inventory is stale.
        setAnalysis(null);
      }
    } catch (error: any) {
      toast.error(error.message || "Couldn't run that change.");
    } finally {
      setIsRunning(false);
    }
  };

  const summary = analysis?.summary;

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-[var(--color-text-primary)] flex items-center gap-2">
            <ScanSearch className="w-4 h-4 text-[var(--color-primary)]" />
            Page Inspector
          </p>
          <p className="text-xs text-[var(--color-text-tertiary)] mt-0.5">
            Reads and edits this page directly — no AI, no waiting, no token cost.
          </p>
        </div>
        <button
          onClick={analyze}
          disabled={isAnalyzing}
          className="flex-shrink-0 px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] text-xs font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-bg)] transition-colors disabled:opacity-60 flex items-center gap-1.5"
        >
          {isAnalyzing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ScanSearch className="w-3.5 h-3.5" />}
          Analyze
        </button>
      </div>

      {summary && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1.5">
            <Stat label="elements" value={summary.element_count} />
            <Stat label="headings" value={summary.headings.length} />
            <Stat label="links" value={summary.links.length} />
            <Stat label="images" value={summary.images.length} />
            <Stat label="forms" value={summary.forms.length} />
            <Stat label="buttons" value={summary.buttons.length} />
            <Stat label="css rules" value={summary.stylesheet.rule_count} />
            <Stat label="words" value={summary.word_count} />
          </div>

          {summary.colors_used.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-[var(--color-text-tertiary)]">Colours:</span>
              {summary.colors_used.slice(0, 12).map((color) => (
                <span
                  key={color}
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[10px] font-mono text-[var(--color-text-secondary)]"
                >
                  <span className="w-2.5 h-2.5 rounded-sm border border-[var(--color-border)]" style={{ background: color }} />
                  {color}
                </span>
              ))}
            </div>
          )}

          {analysis.issues.length > 0 && (
            <div className="rounded-lg border border-[var(--color-warning)] bg-[var(--color-warning-light,transparent)] p-2.5 space-y-1">
              <p className="text-xs font-semibold text-[var(--color-warning)] flex items-center gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5" />
                {analysis.issues.length} thing{analysis.issues.length === 1 ? "" : "s"} worth fixing
              </p>
              {analysis.issues.slice(0, 6).map((issue, i) => (
                <p key={i} className="text-xs text-[var(--color-text-secondary)]">
                  • {issue.message}
                  {issue.index !== null && (
                    <span className="text-[var(--color-text-tertiary)]"> (element {issue.index})</span>
                  )}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      <div>
        <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
          Describe a change
        </label>
        <div className="flex gap-2">
          <input
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                runCommand(false);
              }
            }}
            placeholder='e.g. make the header background #2563eb'
            className="flex-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-xs text-[var(--color-text-primary)] outline-none focus:border-[var(--color-primary)]"
          />
          <button
            onClick={() => runCommand(false)}
            disabled={isRunning || !command.trim()}
            className="px-3 py-2 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center gap-1.5"
          >
            {isRunning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
            Preview
          </button>
        </div>
      </div>

      {result && (
        <div className="space-y-2">
          {result.understood.map((item, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-[var(--color-text-secondary)]">
              <Check className="w-3.5 h-3.5 text-[var(--color-success)] flex-shrink-0 mt-0.5" />
              <span>{item.explanation}</span>
            </div>
          ))}

          {result.not_understood.map((item, i) => (
            <div key={i} className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] p-2.5">
              <p className="text-xs text-[var(--color-text-secondary)] flex items-start gap-2">
                <X className="w-3.5 h-3.5 text-[var(--color-error)] flex-shrink-0 mt-0.5" />
                <span>{item.error}</span>
              </p>
              {item.suggestions?.length > 0 && (
                <div className="mt-2">
                  <p className="text-[10px] text-[var(--color-text-tertiary)] mb-1">Try one of these instead:</p>
                  <div className="flex flex-wrap gap-1">
                    {item.suggestions.slice(0, 6).map((suggestion) => (
                      <button
                        key={suggestion}
                        onClick={() => setCommand(suggestion)}
                        className="px-1.5 py-0.5 rounded border border-[var(--color-border)] bg-[var(--color-surface)] text-[10px] text-[var(--color-text-tertiary)] hover:text-[var(--color-primary)] hover:border-[var(--color-primary)] transition-colors"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}

          {result.understood.length > 0 && !result.applied && (
            <button
              onClick={() => runCommand(true)}
              disabled={isRunning}
              className="w-full px-3 py-2 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-60 flex items-center justify-center gap-1.5"
            >
              {isRunning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              Apply {result.understood.length === 1 ? "this change" : `these ${result.understood.length} changes`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <span className="px-2 py-0.5 rounded-md bg-[var(--color-bg)] border border-[var(--color-border)] text-[10px] text-[var(--color-text-secondary)]">
      <span className="font-semibold text-[var(--color-text-primary)]">{value}</span> {label}
    </span>
  );
}
