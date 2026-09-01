import { NextRequest, NextResponse } from "next/server";

const apiBase = process.env.REGIMPACT_API_BASE_URL ?? "http://localhost:8000";
const organizationId = process.env.REGIMPACT_ORGANIZATION_ID ?? "11111111-1111-4111-8111-111111111111";

export async function POST(request: NextRequest, { params }: { params: Promise<{ obligationId: string }> }) {
  const { obligationId } = await params;
  const mappingId = request.nextUrl.searchParams.get("mapping_id");
  const upstream = await fetch(`${apiBase}/api/v1/obligations/${obligationId}/mapping-decisions${mappingId ? `?mapping_id=${mappingId}` : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Organization-ID": organizationId, "X-Actor-ID": "development:web-analyst" },
    body: await request.text(),
    cache: "no-store",
  });
  return new NextResponse(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json" } });
}
