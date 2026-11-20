import { type NextRequest, NextResponse } from "next/server";

import { loadAuthConfig } from "../../../../../lib/auth/config";
import {
  CSRF_COOKIE,
  SESSION_COOKIE,
  genericAuthError,
} from "../../../../../lib/auth/http";
import { getConsoleAuthService } from "../../../../../lib/auth/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const config = loadAuthConfig();
    if (!config.enabled) return genericAuthError(request, 503);
    const callbackUrl = new URL(config.redirectUri);
    callbackUrl.search = request.nextUrl.search;
    const result = await getConsoleAuthService().completeCallback(
      callbackUrl,
      request.cookies.get(SESSION_COOKIE)?.value,
    );
    const response = NextResponse.redirect(new URL(result.returnTo, config.baseUrl), {
      status: 303,
      headers: { "Cache-Control": "no-store" },
    });
    response.cookies.set(SESSION_COOKIE, result.sessionId, {
      httpOnly: true,
      sameSite: "lax",
      secure: config.cookieSecure,
      path: "/",
      maxAge: config.sessionIdleSeconds,
    });
    response.cookies.set(CSRF_COOKIE, result.csrfToken, {
      httpOnly: false,
      sameSite: "lax",
      secure: config.cookieSecure,
      path: "/",
      maxAge: config.sessionIdleSeconds,
    });
    return response;
  } catch {
    return genericAuthError(request, 401);
  }
}
