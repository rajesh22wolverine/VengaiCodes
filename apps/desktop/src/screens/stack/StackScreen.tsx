import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, CheckCircle2, AlertTriangle, XCircle, Loader2, ChevronRight } from "lucide-react";
import toast from "react-hot-toast";
import apiClient from "@/lib/api";
import BabyTiger from "@/components/baby-tiger/BabyTiger";
import ChatPanel from "@/components/chat/ChatPanel";

interface StackSelection {
  frontend_language: string;
  frontend_framework: string;
  backend_language: string;
  backend_framework: string;
  api_style: string;
}

interface FrontendFrameworkOption {
  key: string;
  label: string;
  languages: string[];
  category: string;
}

interface BackendFrameworkOption {
  key: string;
  label: string;
  languages: string[];
  supported_api_styles: string[];
}

interface StackOptions {
  frontend_frameworks: FrontendFrameworkOption[];
  backend_frameworks: BackendFrameworkOption[];
  api_styles: string[];
  recommended_default: StackSelection;
}

interface StackCombo {
  selection: StackSelection;
  frontend_label: string;
  backend_label: string;
  buildable_now: boolean;
}

interface ValidateResult {
  status: "ok" | "coherent_not_buildable" | "incoherent";
  coherent: boolean;
  buildable_now: boolean;
  coherence_errors: string[];
  message: string;
  suggestion: StackCombo | null;
}

const VALIDATE_DEBOUNCE_MS = 400;

export default function StackScreen() {
  const { id: projectId } = useParams();
  const navigate = useNavigate();

  const [options, setOptions] = useState<StackOptions | null>(null);
  const [selection, setSelection] = useState<StackSelection | null>(null);
  const [validation, setValidation] = useState<ValidateResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isValidating, setIsValidating] = useState(false);
  const [isContinuing, setIsContinuing] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    loadOptions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  useEffect(() => {
    if (!selection) return;
    setIsValidating(true);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runValidate(selection), VALIDATE_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection]);

  const loadOptions = async () => {
    try {
      const { data } = await apiClient.get("/stack/options", { params: { project_id: projectId } });
      setOptions(data);

      let initial: StackSelection = data.recommended_default;
      try {
        const { data: saved } = await apiClient.get(`/stack/${projectId}`);
        if (saved?.selected_stack) {
          const { buildable_now, validated_at, ...rest } = saved.selected_stack;
          initial = rest as StackSelection;
        }
      } catch {
        // No prior selection — use the recommended default.
      }
      setSelection(initial);
    } catch (error: any) {
      toast.error(error.message || "Failed to load stack options.");
      navigate(`/project/${projectId}/uiux`);
    } finally {
      setIsLoading(false);
    }
  };

  const runValidate = async (sel: StackSelection) => {
    try {
      const { data } = await apiClient.post("/stack/validate", { selection: sel });
      setValidation(data);
    } catch (error: any) {
      toast.error(error.message || "Failed to validate stack.");
    } finally {
      setIsValidating(false);
    }
  };

  const handleContinue = async () => {
    if (!selection) return;
    setIsContinuing(true);
    try {
      await apiClient.post("/stack/select", { project_id: projectId, selection });
      toast.success("Stack saved! Next: Architecture 🐯");
      navigate(`/project/${projectId}/architecture`);
    } catch (error: any) {
      toast.error(error.message || "Failed to save stack.");
    } finally {
      setIsContinuing(false);
    }
  };

  const useSuggestion = () => {
    if (!validation?.suggestion) return;
    setSelection(validation.suggestion.selection);
  };

  const updateFrontendFramework = (frameworkKey: string) => {
    if (!options || !selection) return;
    const framework = options.frontend_frameworks.find((f) => f.key === frameworkKey);
    if (!framework) return;
    const language = framework.languages.includes(selection.frontend_language)
      ? selection.frontend_language
      : framework.languages[0] || selection.frontend_language;
    setSelection({ ...selection, frontend_framework: frameworkKey, frontend_language: language });
  };

  const updateBackendFramework = (frameworkKey: string) => {
    if (!options || !selection) return;
    const framework = options.backend_frameworks.find((f) => f.key === frameworkKey);
    if (!framework) return;
    const language = framework.languages.includes(selection.backend_language)
      ? selection.backend_language
      : framework.languages[0] || selection.backend_language;
    const apiStyle = framework.supported_api_styles.includes(selection.api_style)
      ? selection.api_style
      : framework.supported_api_styles[0] || selection.api_style;
    setSelection({
      ...selection,
      backend_framework: frameworkKey,
      backend_language: language,
      api_style: apiStyle,
    });
  };

  if (isLoading || !options || !selection) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-4 bg-[var(--color-background)]">
        <BabyTiger size={100} expression="thinking" />
        <p className="text-[var(--color-text-secondary)] text-sm">Loading tech stack options...</p>
      </div>
    );
  }

  const selectedFrontend = options.frontend_frameworks.find((f) => f.key === selection.frontend_framework);
  const selectedBackend = options.backend_frameworks.find((f) => f.key === selection.backend_framework);
  const canContinue = validation?.status === "ok";
  const canContinueAnyway = validation?.status === "coherent_not_buildable";

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
        <BabyTiger size={36} expression="idle" />
        <div className="flex-1">
          <h1 className="text-sm font-semibold text-[var(--color-text-primary)]">Tech Stack</h1>
          <p className="text-xs text-[var(--color-text-tertiary)]">Before Architecture — pick your UI, backend, and API style</p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="max-w-2xl mx-auto space-y-5">
          <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
            Pick any combination you like — Baby Tiger checks every possibility and tells you
            immediately whether it's possible, and what's closest if it isn't.
          </p>

          <ChoicePickerRow
            label="UI Framework"
            options={options.frontend_frameworks.map((f) => ({ key: f.key, label: f.label }))}
            value={selection.frontend_framework}
            onChange={updateFrontendFramework}
          />
          {selectedFrontend && selectedFrontend.languages.length > 1 && (
            <ChoicePickerRow
              label="UI Language"
              options={selectedFrontend.languages.map((l) => ({ key: l, label: titleCase(l) }))}
              value={selection.frontend_language}
              onChange={(lang) => setSelection({ ...selection, frontend_language: lang })}
              indent
            />
          )}

          <ChoicePickerRow
            label="Backend Framework"
            options={options.backend_frameworks.map((f) => ({ key: f.key, label: f.label }))}
            value={selection.backend_framework}
            onChange={updateBackendFramework}
          />
          {selectedBackend && selectedBackend.languages.length > 1 && (
            <ChoicePickerRow
              label="Backend Language"
              options={selectedBackend.languages.map((l) => ({ key: l, label: titleCase(l) }))}
              value={selection.backend_language}
              onChange={(lang) => setSelection({ ...selection, backend_language: lang })}
              indent
            />
          )}

          <ChoicePickerRow
            label="API Style"
            options={options.api_styles.map((a) => ({
              key: a,
              label: a.toUpperCase(),
              disabled: !!selectedBackend && !selectedBackend.supported_api_styles.includes(a),
            }))}
            value={selection.api_style}
            onChange={(style) => setSelection({ ...selection, api_style: style })}
          />

          {/* Validation banner */}
          <div className="min-h-[3.5rem]">
            {isValidating ? (
              <div className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)] px-1">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Checking...
              </div>
            ) : validation?.status === "ok" ? (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="rounded-xl border border-[var(--color-success)] bg-[var(--color-success-light)] px-4 py-3 flex items-center gap-2"
              >
                <CheckCircle2 className="w-4 h-4 text-[var(--color-success)] flex-shrink-0" />
                <p className="text-xs text-[var(--color-text-primary)]">{validation.message}</p>
              </motion.div>
            ) : validation?.status === "coherent_not_buildable" ? (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="rounded-xl border border-[var(--color-warning)] bg-[var(--color-warning-light)] px-4 py-3 space-y-2"
              >
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-[var(--color-warning)] flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-[var(--color-text-primary)] leading-relaxed">
                    {validation.message}
                    {validation.suggestion && (
                      <> Nearest buildable: <span className="font-semibold">{validation.suggestion.frontend_label} + {validation.suggestion.backend_label}</span>.</>
                    )}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={useSuggestion}
                    className="px-3 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors"
                  >
                    Use Suggested Stack
                  </button>
                </div>
              </motion.div>
            ) : validation?.status === "incoherent" ? (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="rounded-xl border border-[var(--color-error)] bg-[var(--color-error-light)] px-4 py-3 space-y-2"
              >
                <div className="flex items-start gap-2">
                  <XCircle className="w-4 h-4 text-[var(--color-error)] flex-shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    {validation.coherence_errors.map((err, i) => (
                      <p key={i} className="text-xs text-[var(--color-text-primary)] leading-relaxed">{err}</p>
                    ))}
                  </div>
                </div>
                {validation.suggestion && (
                  <div className="flex items-center gap-2">
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      Nearest possible: <span className="font-semibold text-[var(--color-text-primary)]">{validation.suggestion.frontend_label} + {validation.suggestion.backend_label}</span>
                    </p>
                    <button
                      onClick={useSuggestion}
                      className="px-3 py-1.5 rounded-lg bg-[var(--color-primary)] text-white text-xs font-semibold hover:bg-[var(--color-primary-hover)] transition-colors flex-shrink-0"
                    >
                      Use This
                    </button>
                  </div>
                )}
              </motion.div>
            ) : null}
          </div>

          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={handleContinue}
              disabled={!canContinue || isContinuing}
              className="flex-1 py-3 rounded-xl bg-[var(--color-primary)] text-white font-semibold text-sm hover:bg-[var(--color-primary-hover)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {isContinuing ? <Loader2 className="w-4 h-4 animate-spin" /> : <ChevronRight className="w-4 h-4" />}
              Continue
            </button>
            {canContinueAnyway && (
              <button
                onClick={handleContinue}
                disabled={isContinuing}
                className="px-4 py-3 rounded-xl border border-[var(--color-border)] text-[var(--color-text-secondary)] text-xs font-medium hover:bg-[var(--color-surface-raised)] transition-colors disabled:opacity-60"
              >
                Continue Anyway (docs only)
              </button>
            )}
          </div>
        </div>
      </div>

      <ChatPanel projectId={projectId} phase="stack" />
    </div>
  );
}

function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function ChoicePickerRow({
  label,
  options,
  value,
  onChange,
  indent,
}: {
  label: string;
  options: { key: string; label: string; disabled?: boolean }[];
  value: string;
  onChange: (key: string) => void;
  indent?: boolean;
}) {
  return (
    <div className={indent ? "pl-4" : undefined}>
      <p className="text-xs font-semibold text-[var(--color-text-primary)] mb-2">{label}</p>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => (
          <button
            key={opt.key}
            onClick={() => !opt.disabled && onChange(opt.key)}
            disabled={opt.disabled}
            title={opt.disabled ? "Not supported by the selected backend" : undefined}
            className={`px-3 py-1.5 rounded-lg border text-xs font-medium transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
              value === opt.key
                ? "border-[var(--color-primary)] text-[var(--color-primary)] bg-[var(--color-primary-light)]"
                : "border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-surface-raised)]"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}
