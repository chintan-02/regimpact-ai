import { cookies } from "next/headers";

const apiBase = process.env.REGIMPACT_API_BASE_URL ?? "http://localhost:8000";

export async function POST(_request: Request, context: { params: Promise<{ jobId: string }> }) {
  const token = (await cookies()).get("regimpact_access_token")?.value;
  const { jobId } = await context.params;
  if (!token) return Response.json({ detail: "Authentication required" }, { status: 401 });
  const response = await fetch(`${apiBase}/api/v1/ingestions/${jobId}/replay`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  const payload = await response.json();
  return Response.json(payload, { status: response.status });
}
