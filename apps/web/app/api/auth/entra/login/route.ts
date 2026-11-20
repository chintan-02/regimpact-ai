import { type NextRequest, NextResponse } from "next/server";

import { genericAuthError } from "../../../../../lib/auth/http";
import { getConsoleAuthService } from "../../../../../lib/auth/runtime";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const result = await getConsoleAuthService().beginLogin(
      request.nextUrl.searchParams.get("return_to"),
    );
    return NextResponse.redirect(result.authorizationUrl, {
      status: 302,
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return genericAuthError(request, 503);
  }
}
