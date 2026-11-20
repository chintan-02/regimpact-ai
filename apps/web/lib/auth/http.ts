import { randomUUID } from "node:crypto";

import { NextResponse } from "next/server";

const REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

export const SESSION_COOKIE = "regimpact_session";
export const CSRF_COOKIE = "regimpact_csrf";
export const CSRF_HEADER = "X-CSRF-Token";

export function requestId(request: Request): string {
  const candidate = request.headers.get("X-Request-ID");
  return candidate && REQUEST_ID.test(candidate) ? candidate : randomUUID();
}

export function genericAuthError(request: Request, status: 401 | 503): NextResponse {
  const id = requestId(request);
  return NextResponse.json(
    {
      error: {
        code: status === 401 ? "authentication_failed" : "authentication_unavailable",
        message: status === 401 ? "Authentication failed" : "Authentication unavailable",
      },
      request_id: id,
    },
    { status, headers: { "X-Request-ID": id, "Cache-Control": "no-store" } },
  );
}

export function clearAuthCookies(response: NextResponse, secure: boolean): void {
  for (const name of [SESSION_COOKIE, CSRF_COOKIE]) {
    response.cookies.set(name, "", {
      httpOnly: name === SESSION_COOKIE,
      sameSite: "lax",
      secure,
      path: "/",
      maxAge: 0,
    });
  }
}
