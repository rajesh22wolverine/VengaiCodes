import { describe, expect, it } from "vitest";
import { maskEmail } from "./format";

// maskEmail mirrors the backend's mask_email(). It is what the user sees on
// the OTP screen to confirm which address a code went to, so a wrong mask
// either leaks the address or makes it unrecognisable.
describe("maskEmail", () => {
  it("keeps the first two characters and the whole domain", () => {
    expect(maskEmail("rajesh22wolverine@gmail.com")).toBe("ra***************@gmail.com");
  });

  it("masks every character after the first two", () => {
    const masked = maskEmail("abcdef@example.com");
    expect(masked).toBe("ab****@example.com");
    expect(masked.split("@")[0]).toHaveLength("abcdef".length);
  });

  it("still hides something when the local part is very short", () => {
    // <= 2 chars takes the other branch: first char + a single star.
    expect(maskEmail("ab@x.com")).toBe("a*@x.com");
    expect(maskEmail("a@x.com")).toBe("a*@x.com");
  });

  it("preserves a Gmail +suffix address's domain untouched", () => {
    // The project's whole test-account convention relies on + addressing.
    expect(maskEmail("rajesh22wolverine+kalkitest2@gmail.com")).toMatch(/@gmail\.com$/);
  });

  it("returns the input unchanged when there is no domain to mask around", () => {
    expect(maskEmail("notanemail")).toBe("notanemail");
    expect(maskEmail("")).toBe("");
  });

  it("never returns the original local part for a maskable address", () => {
    const email = "rajesh22wolverine@gmail.com";
    expect(maskEmail(email)).not.toBe(email);
    expect(maskEmail(email)).not.toContain("wolverine");
  });
});
