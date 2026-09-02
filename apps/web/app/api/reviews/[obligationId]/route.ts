import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";

const apiBase = process.env.REGIMPACT_API_BASE_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest, { params }: { params: Promise<{ obligationId: string }> }) {
  const { obligationId } = await params;
  const token = (await cookies()).get("regimpact_access_token")?.value;
  if (!token) return NextResponse.json({ error: "Unauthenticated" }, { status: 401 });
  const mappingId = request.nextUrl.searchParams.get("mapping_id");
  const upstream = await fetch(`${apiBase}/api/v1/obligations/${obligationId}/mapping-decisions${mappingId ? `?mapping_id=${mappingId}` : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: await request.text(),
    cache: "no-store",
  });
  return new NextResponse(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json" } });
}
