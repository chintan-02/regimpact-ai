import { NextResponse } from "next/server";

export async function GET() {
  const environment = (process.env.REGIMPACT_ENVIRONMENT ?? "local").toLowerCase();
  const enabled = process.env.REGIMPACT_DEMO_MODE === "true" && !["production", "prod"].includes(environment);
  return NextResponse.json({ enabled });
}
