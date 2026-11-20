import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, genericAuthError } from "../../../../../lib/auth/http";
import { getConsoleAuthService } from "../../../../../lib/auth/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const sessionId = request.cookies.get(SESSION_COOKIE)?.value;
    if (!sessionId) return genericAuthError(request, 401);
    await getConsoleAuthService().getSession(sessionId);
    return NextResponse.json(
      { authenticated: true },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return genericAuthError(request, 401);
  }
}
