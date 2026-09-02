import { NextResponse } from "next/server";

const apiBase = process.env.REGIMPACT_API_BASE_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const response = await fetch(`${apiBase}/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
    if (!response.ok) {
      return NextResponse.json({ status: "not_ready" }, { status: 503 });
    }
    const payload = (await response.json()) as { status?: string; version?: string };
    if (payload.status !== "ready") {
      return NextResponse.json({ status: "not_ready" }, { status: 503 });
    }
    return NextResponse.json({ status: "ready", version: payload.version });
  } catch {
    return NextResponse.json({ status: "not_ready" }, { status: 503 });
  }
}
