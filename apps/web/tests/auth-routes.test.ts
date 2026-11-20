import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { testConfig } from "./auth-helpers";

const mocks = vi.hoisted(() => ({
  config: undefined as ReturnType<typeof testConfig> | undefined,
  beginLogin: vi.fn(),
  completeCallback: vi.fn(),
  logout: vi.fn(),
  getSession: vi.fn(),
}));

vi.mock("../lib/auth/runtime", () => ({
  getConsoleAuthService: () => ({
    beginLogin: mocks.beginLogin,
    completeCallback: mocks.completeCallback,
    logout: mocks.logout,
    getSession: mocks.getSession,
  }),
}));

vi.mock("../lib/auth/config", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/auth/config")>();
  return { ...actual, loadAuthConfig: () => mocks.config };
});

import { GET as callback } from "../app/api/auth/entra/callback/route";
import { GET as login } from "../app/api/auth/entra/login/route";
import { POST as logout } from "../app/api/auth/entra/logout/route";
import { GET as session } from "../app/api/auth/entra/session/route";

describe("browser-facing Entra routes", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.config = testConfig();
  });

  it("redirects login without exposing protocol secrets", async () => {
    mocks.beginLogin.mockResolvedValue({
      authorizationUrl: new URL("http://127.0.0.1/authorize?state=opaque&code_challenge=challenge"),
    });
    const response = await login(
      new NextRequest("http://localhost:3000/api/auth/entra/login?return_to=%2Freview"),
    );
    expect(response.status).toBe(302);
    const location = response.headers.get("location") ?? "";
    expect(location).toContain("state=opaque");
    expect(location).not.toContain("access_token");
    expect(location).not.toContain("refresh_token");
  });

  it("sets only opaque session and CSRF cookies after callback", async () => {
    mocks.completeCallback.mockResolvedValue({
      sessionId: "opaque-session-value-that-is-long-enough-1234567890",
      csrfToken: "opaque-csrf-value-that-is-long-enough-123456789012",
      returnTo: "/review",
    });
    const response = await callback(
      new NextRequest("http://localhost:3000/api/auth/entra/callback?code=code&state=state"),
    );
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("http://localhost:3000/review");
    const cookies = response.headers.getSetCookie().join("\n");
    expect(cookies).toContain("regimpact_session=");
    expect(cookies).toContain("regimpact_csrf=");
    expect(cookies).toContain("HttpOnly");
    expect(cookies).toContain("SameSite=lax");
    for (const forbidden of ["access_token", "refresh_token", "id_token", "Bearer "]) {
      expect(cookies).not.toContain(forbidden);
      expect(response.headers.get("location")).not.toContain(forbidden);
    }
  });

  it("requires a session and CSRF header for logout and clears cookies", async () => {
    const missing = await logout(
      new NextRequest("http://localhost:3000/api/auth/entra/logout", { method: "POST" }),
    );
    expect(missing.status).toBe(401);
    expect(mocks.logout).not.toHaveBeenCalled();

    const response = await logout(
      new NextRequest("http://localhost:3000/api/auth/entra/logout", {
        method: "POST",
        headers: {
          Cookie: "regimpact_session=opaque-session-value-that-is-long-enough-1234567890",
          "X-CSRF-Token": "opaque-csrf-value-that-is-long-enough-123456789012",
        },
      }),
    );
    expect(response.status).toBe(200);
    expect(mocks.logout).toHaveBeenCalledTimes(1);
    expect(response.headers.getSetCookie().join("\n")).toContain("Max-Age=0");
  });

  it("returns only authentication status from the protected session route", async () => {
    mocks.getSession.mockResolvedValue({ subject: "must-not-be-returned" });
    const response = await session(
      new NextRequest("http://localhost:3000/api/auth/entra/session", {
        headers: {
          Cookie: "regimpact_session=opaque-session-value-that-is-long-enough-1234567890",
        },
      }),
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ authenticated: true });
  });

  it("returns generic correlated failures", async () => {
    mocks.beginLogin.mockRejectedValue(new Error("token secret claim"));
    const response = await login(
      new NextRequest("http://localhost:3000/api/auth/entra/login", {
        headers: { "X-Request-ID": "safe-request-id" },
      }),
    );
    expect(response.status).toBe(503);
    expect(response.headers.get("X-Request-ID")).toBe("safe-request-id");
    const body = JSON.stringify(await response.json());
    expect(body).not.toContain("token secret claim");
  });
});
