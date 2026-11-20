import { type NextRequest, NextResponse } from "next/server";

import { loadAuthConfig } from "../../../../../lib/auth/config";
import {
  CSRF_HEADER,
  SESSION_COOKIE,
  clearAuthCookies,
  genericAuthError,
} from "../../../../../lib/auth/http";
import { getConsoleAuthService } from "../../../../../lib/auth/runtime";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest): Promise<NextResponse> {
  let secure = true;
  try {
    const config = loadAuthConfig();
    if (!config.enabled) return genericAuthError(request, 503);
    secure = config.cookieSecure;
    const sessionId = request.cookies.get(SESSION_COOKIE)?.value;
    const csrfToken = request.headers.get(CSRF_HEADER);
    if (!sessionId || !csrfToken) return genericAuthError(request, 401);
    await getConsoleAuthService().logout(sessionId, csrfToken);
    const response = NextResponse.json(
      { signed_out: true },
      { headers: { "Cache-Control": "no-store" } },
    );
    clearAuthCookies(response, secure);
    return response;
  } catch {
    const response = genericAuthError(request, 401);
    clearAuthCookies(response, secure);
    return response;
  }
}
