import { describe, expect, it } from "vitest";
import reducer, {
  clearError,
  clearOTPState,
  updateUser,
  loginUser,
  logoutUser,
  checkSession,
  type User,
} from "./authSlice";

/** Minimal User matching the backend's UserResponse shape. */
function makeUser(overrides: Partial<User> = {}): User {
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
    ...overrides,
  } as User;
}

const loggedOut = reducer(undefined, { type: "@@INIT" });

describe("authSlice initial state", () => {
  it("starts logged out with nothing pending", () => {
    expect(loggedOut.user).toBeNull();
    expect(loggedOut.isAuthenticated).toBe(false);
    expect(loggedOut.isLoading).toBe(false);
    expect(loggedOut.error).toBeNull();
  });
});

describe("login lifecycle", () => {
  it("clears any previous error while the request is in flight", () => {
    const withError = { ...loggedOut, error: "Incorrect username/email or password." };
    const next = reducer(withError, { type: loginUser.pending.type });

    expect(next.isLoading).toBe(true);
    expect(next.error).toBeNull();
  });

  it("stores the user and marks the session authenticated on success", () => {
    const user = makeUser();
    const next = reducer(loggedOut, { type: loginUser.fulfilled.type, payload: user });

    expect(next.isAuthenticated).toBe(true);
    expect(next.user).toEqual(user);
    expect(next.isLoading).toBe(false);
  });

  it("does NOT authenticate on a rejected login", () => {
    // Guards the worst failure mode in this slice: a rejected login that
    // still flips isAuthenticated would let the router into the app shell.
    const next = reducer(loggedOut, {
      type: loginUser.rejected.type,
      payload: "Incorrect username/email or password.",
    });

    expect(next.isAuthenticated).toBe(false);
    expect(next.user).toBeNull();
    expect(next.error).toBe("Incorrect username/email or password.");
    expect(next.isLoading).toBe(false);
  });
});

describe("admin flag round-trips", () => {
  // Regression cover: both frontend User interfaces omitted `is_admin`
  // even though the backend always sent it, so the admin nav entry could
  // never render. These assert the flag survives the paths that touch user
  // state, which is what gates AdminRoute and the sidebar entry.
  it("preserves is_admin through login", () => {
    const next = reducer(loggedOut, {
      type: loginUser.fulfilled.type,
      payload: makeUser({ is_admin: true }),
    });

    expect(next.user?.is_admin).toBe(true);
  });

  it("preserves is_admin through a partial updateUser", () => {
    const authed = reducer(loggedOut, {
      type: loginUser.fulfilled.type,
      payload: makeUser({ is_admin: true }),
    });

    const next = reducer(authed, updateUser({ projects_used: 3 }));

    expect(next.user?.projects_used).toBe(3);
    expect(next.user?.is_admin).toBe(true);
    expect(next.user?.username).toBe("kalkitiger");
  });

  it("preserves is_admin through a session restore", () => {
    const next = reducer(loggedOut, {
      type: checkSession.fulfilled.type,
      payload: makeUser({ is_admin: true }),
    });

    expect(next.user?.is_admin).toBe(true);
    expect(next.isAuthenticated).toBe(true);
  });
});

describe("updateUser", () => {
  it("is a no-op when nobody is logged in", () => {
    const next = reducer(loggedOut, updateUser({ projects_used: 9 }));
    expect(next.user).toBeNull();
  });

  it("merges token-quota fields without dropping the rest", () => {
    const authed = reducer(loggedOut, {
      type: loginUser.fulfilled.type,
      payload: makeUser(),
    });

    const next = reducer(
      authed,
      updateUser({ ai_tokens_used: 38, ai_tokens_remaining: 199962 })
    );

    expect(next.user?.ai_tokens_used).toBe(38);
    expect(next.user?.ai_tokens_remaining).toBe(199962);
    expect(next.user?.ai_tokens_limit).toBe(200000);
    expect(next.user?.email).toBe("rajesh22wolverine+test@gmail.com");
  });
});

describe("session teardown", () => {
  it("clears user, auth flag and error on logout", () => {
    const authed = {
      ...reducer(loggedOut, { type: loginUser.fulfilled.type, payload: makeUser() }),
      error: "stale error",
    };

    const next = reducer(authed, { type: logoutUser.fulfilled.type });

    expect(next.user).toBeNull();
    expect(next.isAuthenticated).toBe(false);
    expect(next.error).toBeNull();
  });

  it("drops the session when checkSession is rejected", () => {
    const authed = reducer(loggedOut, {
      type: loginUser.fulfilled.type,
      payload: makeUser(),
    });

    const next = reducer(authed, { type: checkSession.rejected.type });

    expect(next.user).toBeNull();
    expect(next.isAuthenticated).toBe(false);
  });
});

describe("plain reducers", () => {
  it("clearError removes only the error", () => {
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
