// Mirrors AIConfigCreate.label's max_length=100 in
// apps/backend/app/schemas/ai_config.py. Real-world .gguf filenames
// (org--repo--quant-details.gguf) routinely exceed this on their own,
// so the label built from them must be clamped before it's sent —
// otherwise the backend 422s and the save silently fails.
export const PORTABLE_LABEL_MAX_LENGTH = 100;
export const PORTABLE_LABEL_SUFFIX = " (USB)";

export function buildPortableLabel(displayName: string): string {
  const maxNameLength = PORTABLE_LABEL_MAX_LENGTH - PORTABLE_LABEL_SUFFIX.length;
  const name =
    displayName.length > maxNameLength
      ? `${displayName.slice(0, maxNameLength - 1)}…`
      : displayName;
  return `${name}${PORTABLE_LABEL_SUFFIX}`;
}
