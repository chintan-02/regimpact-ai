import { cookies } from "next/headers";

const apiBase = process.env.REGIMPACT_API_BASE_URL ?? "http://localhost:8000";

export async function POST(request: Request) {
  const token = (await cookies()).get("regimpact_access_token")?.value;
  if (!token) return Response.json({ detail: "Authentication required" }, { status: 401 });
  const response = await fetch(`${apiBase}/api/v1/agent-workflows`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(await request.json()),
    cache: "no-store",
  });
  return Response.json(await response.json(), { status: response.status });
}
