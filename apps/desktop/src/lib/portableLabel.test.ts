import { describe, expect, it } from "vitest";
import {
  buildPortableLabel,
  PORTABLE_LABEL_MAX_LENGTH,
  PORTABLE_LABEL_SUFFIX,
} from "./portableLabel";

// Regression cover for a real bug: the portable-model label was built as
// `${display_name} (USB)` with no clamp, but the backend's
// AIConfigCreate.label has max_length=100. Real .gguf filenames blow past
// that on their own, so saving a portable model 422'd forever with no
// visible cause. The invariant that actually matters to the backend is the
// length ceiling — assert that first and hardest.
describe("buildPortableLabel", () => {
  it("appends the USB suffix to a short name unchanged", () => {
    expect(buildPortableLabel("phi3")).toBe("phi3 (USB)");
  });

  it("never exceeds the backend's max_length=100, whatever the input", () => {
    const realisticGguf =
      "TheBloke--Mistral-7B-Instruct-v0.2-GGUF--mistral-7b-instruct-v0.2.Q4_K_M.gguf";
    const absurd = "x".repeat(5000);

    for (const name of ["phi3", realisticGguf, absurd]) {
      expect(buildPortableLabel(name).length).toBeLessThanOrEqual(
        PORTABLE_LABEL_MAX_LENGTH
      );
    }
  });

  it("truncates with an ellipsis and keeps the suffix when over the limit", () => {
    const label = buildPortableLabel("y".repeat(200));

    expect(label.endsWith(PORTABLE_LABEL_SUFFIX)).toBe(true);
    expect(label).toContain("…");
    expect(label.length).toBe(PORTABLE_LABEL_MAX_LENGTH);
  });

  it("leaves a name that exactly fits untouched", () => {
    // The longest name that needs no truncation.
    const exact = "z".repeat(PORTABLE_LABEL_MAX_LENGTH - PORTABLE_LABEL_SUFFIX.length);
    const label = buildPortableLabel(exact);

    expect(label).toBe(`${exact}${PORTABLE_LABEL_SUFFIX}`);
    expect(label).not.toContain("…");
    expect(label.length).toBe(PORTABLE_LABEL_MAX_LENGTH);
  });

  it("handles an empty name without producing a bare suffix crash", () => {
    expect(buildPortableLabel("")).toBe(PORTABLE_LABEL_SUFFIX);
  });
});
