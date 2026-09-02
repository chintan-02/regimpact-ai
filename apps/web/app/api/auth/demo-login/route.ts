import { NextRequest, NextResponse } from "next/server";

const apiBase = process.env.REGIMPACT_API_BASE_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  const upstream = await fetch(`${apiBase}/api/v1/auth/demo-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  const body = await upstream.json();
  if (!upstream.ok) return NextResponse.json({ error: "Demo access is unavailable" }, { status: upstream.status });
  const response = NextResponse.json(body.user);
  response.cookies.set("regimpact_access_token", body.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.REGIMPACT_COOKIE_SECURE === "true",
    path: "/",
    maxAge: body.expires_in,
  });
  return response;
}
