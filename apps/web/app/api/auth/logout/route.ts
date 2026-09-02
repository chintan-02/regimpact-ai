import { NextResponse } from "next/server";

export async function POST() {
  const response = NextResponse.json({ signed_out: true });
  response.cookies.set("regimpact_access_token", "", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.REGIMPACT_COOKIE_SECURE === "true",
    path: "/",
    maxAge: 0,
  });
  return response;
}
