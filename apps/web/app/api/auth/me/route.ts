import { cookies } from "next/headers";
import { NextResponse } from "next/server";

const apiBase = process.env.REGIMPACT_API_BASE_URL ?? "http://localhost:8000";

export async function GET() {
  const token = (await cookies()).get("regimpact_access_token")?.value;
  if (!token) return NextResponse.json({ error: "Unauthenticated" }, { status: 401 });
  const upstream = await fetch(`${apiBase}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
