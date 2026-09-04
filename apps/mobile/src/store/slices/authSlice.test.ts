import { describe, expect, it, vi } from "vitest";

// authSlice -> api.ts -> storage.ts -> expo-secure-store / AsyncStorage.
// Mock the native leaf so the reducers can be tested in plain node.
vi.mock("@/lib/storage", () => ({
  getAccessToken: vi.fn().mockResolvedValue(null),
  setTokens: vi.fn().mockResolvedValue(undefined),
  clearTokens: vi.fn().mockResolvedValue(undefined),
}));

import reducer, {
  clearError,
  clearOTPState,
  updateUser,
  loginUser,
  logoutUser,
  checkSession,
  type User,
} from "./authSlice";

function makeUser(overrides: Record<string, unknown> = {}) {
  return {
    id: "u1",
    full_name: "Test Tiger",
    username: "kalkitiger",
    email: "rajesh22wolverine+test@gmail.com",
    tier: "free",
    is_admin: false,
    is_vip: false,
    projects_used: 0,
    projects_limit: 1,
    projects_remaining: 1,
    ai_tokens_used: 0,
    ai_tokens_limit: 200000,
    ai_tokens_remaining: 200000,
    email_verified: true,
    mobile_verified: false,
    govt_id_verified: false,
    biometric_verified: false,
    verification_status: "unverified",
    is_seller: false,
    seller_verified: false,
    seller_rating: 0,
    total_apps_sold: 0,
    has_custom_voice: false,
    has_custom_character: false,
    revenue_sharing_agreed: false,
    status: "active",
    restriction_level: "none",
    created_at: "2026-09-04T00:00:00Z",
    preferences: {},
    ...overrides,
  };
}

const loggedOut = reducer(undefined, { type: "@@INIT" });

describe("initial state", () => {
  it("starts logged out with the session not yet checked", () => {
    expect(loggedOut.user).toBeNull();
    expect(loggedOut.isAuthenticated).toBe(false);
    expect(loggedOut.sessionChecked).toBe(false);
  });
});

describe("sessionChecked", () => {
  // The flag exists so a splash screen can tell "still checking" apart from
  // "checked, and there is no session". That only works if it flips on BOTH
  // outcomes — a flag set only on success would hang the splash forever for
  // logged-out users.
  //
  // NOTE: nothing currently reads sessionChecked anywhere in apps/mobile.
  // These assertions lock in the correct contract for whenever it is wired up.
  it("is set when a session is successfully restored", () => {
    const next = reducer(loggedOut, {
      type: checkSession.fulfilled.type,
      payload: makeUser(),
    });

    expect(next.sessionChecked).toBe(true);
    expect(next.isAuthenticated).toBe(true);
  });

  it("is ALSO set when there is no session to restore", () => {
    const next = reducer(loggedOut, { type: checkSession.rejected.type });

    expect(next.sessionChecked).toBe(true);
    expect(next.isAuthenticated).toBe(false);
    expect(next.user).toBeNull();
  });

  it("stays true after logging out", () => {
    // Logging out does not un-check the session; the app already knows.
    const restored = reducer(loggedOut, {
      type: checkSession.fulfilled.type,
      payload: makeUser(),
    });
    const next = reducer(restored, { type: logoutUser.fulfilled.type });

    expect(next.sessionChecked).toBe(true);
    expect(next.isAuthenticated).toBe(false);
  });
});

describe("login lifecycle", () => {
  it("authenticates and stores the user on success", () => {
    const user = makeUser();
    const next = reducer(loggedOut, { type: loginUser.fulfilled.type, payload: user });

    expect(next.isAuthenticated).toBe(true);
    expect(next.user).toEqual(user);
  });

  it("does NOT authenticate on a rejected login", () => {
    const next = reducer(loggedOut, {
      type: loginUser.rejected.type,
      payload: "Incorrect username/email or password.",
    });

    expect(next.isAuthenticated).toBe(false);
    expect(next.user).toBeNull();
    expect(next.error).toBe("Incorrect username/email or password.");
  });
});

describe("admin flag round-trips", () => {
  // The mobile Settings screen shows the Admin entry only when
  // user?.is_admin is true, and the User interface once omitted the field
  // entirely — so the entry could never appear.
  it("survives login", () => {
    const next = reducer(loggedOut, {
      type: loginUser.fulfilled.type,
      payload: makeUser({ is_admin: true }),
    });
    expect(next.user?.is_admin).toBe(true);
  });

  it("survives a partial updateUser", () => {
    const authed = reducer(loggedOut, {
      type: loginUser.fulfilled.type,
      payload: makeUser({ is_admin: true }),
    });
    const next = reducer(authed, updateUser({ ai_tokens_used: 38 } as Partial<User>));

    expect(next.user?.is_admin).toBe(true);
    expect(next.user?.ai_tokens_used).toBe(38);
    expect(next.user?.username).toBe("kalkitiger");
  });

  it("survives a session restore", () => {
    const next = reducer(loggedOut, {
      type: checkSession.fulfilled.type,
      payload: makeUser({ is_admin: true }),
    });
    expect(next.user?.is_admin).toBe(true);
  });
});

describe("logout teardown", () => {
  it("clears user, auth flag, error and any in-flight OTP state", () => {
    // Mobile clears OTP state on logout where desktop does not — leaving a
    // stale otpTarget would leak the previous account's address onto the
    // next user's OTP screen.
    const dirty = {
      ...reducer(loggedOut, { type: loginUser.fulfilled.type, payload: makeUser() }),
      error: "stale",
      otpSent: true,
      otpTarget: "rajesh22wolverine@gmail.com",
      otpType: "email" as const,
      otpPurpose: "signup" as const,
    };

    const next = reducer(dirty, { type: logoutUser.fulfilled.type });

    expect(next.user).toBeNull();
    expect(next.isAuthenticated).toBe(false);
    expect(next.error).toBeNull();
    expect(next.otpSent).toBe(false);
    expect(next.otpTarget).toBeNull();
  });
});

describe("plain reducers", () => {
  it("updateUser is a no-op when logged out", () => {
    expect(reducer(loggedOut, updateUser({ projects_used: 9 } as Partial<User>)).user).toBeNull();
  });

  it("clearError leaves the session intact", () => {
    const authed = {
      ...reducer(loggedOut, { type: loginUser.fulfilled.type, payload: makeUser() }),
      error: "boom",
    };
    const next = reducer(authed, clearError());

    expect(next.error).toBeNull();
    expect(next.isAuthenticated).toBe(true);
  });

  it("clearOTPState resets every OTP field together", () => {
    const mid = {
      ...loggedOut,
      otpSent: true,
      otpTarget: "rajesh22wolverine@gmail.com",
      otpType: "email" as const,
      otpPurpose: "signup" as const,
    };
    const next = reducer(mid, clearOTPState());

    expect(next.otpSent).toBe(false);
    expect(next.otpTarget).toBeNull();
    expect(next.otpType).toBeNull();
    expect(next.otpPurpose).toBeNull();
  });
});
