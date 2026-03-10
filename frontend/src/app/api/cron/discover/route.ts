import { NextRequest, NextResponse } from "next/server";

/**
 * Daily cron job — triggers role discovery + auto-scoring on the backend.
 *
 * Vercel Cron calls this route on schedule (see vercel.json).
 * This route forwards the request to the FastAPI backend's /discover/cron endpoint.
 *
 * Required env vars (set in Vercel project settings):
 *   BACKEND_URL  — e.g. https://your-railway-app.up.railway.app
 *   CRON_SECRET  — shared secret matching the backend's CRON_SECRET
 */
export async function GET(request: NextRequest) {
  // Vercel Cron sends a bearer token to verify the request is from Vercel
  const authHeader = request.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;

  if (!cronSecret) {
    return NextResponse.json(
      { error: "CRON_SECRET not configured" },
      { status: 500 }
    );
  }

  // Verify the request came from Vercel Cron (or has the correct secret)
  if (authHeader !== `Bearer ${cronSecret}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const backendUrl =
    process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_BASE;
  if (!backendUrl) {
    return NextResponse.json(
      { error: "BACKEND_URL not configured" },
      { status: 500 }
    );
  }

  try {
    const res = await fetch(`${backendUrl}/discover/cron`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${cronSecret}`,
        "Content-Type": "application/json",
      },
      // Allow up to 5 minutes for full discovery + scoring
      signal: AbortSignal.timeout(300_000),
    });

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: "Backend cron failed", detail: data },
        { status: res.status }
      );
    }

    return NextResponse.json({
      status: "completed",
      trigger: "vercel_cron",
      ...data,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json(
      { error: "Cron request failed", detail: message },
      { status: 500 }
    );
  }
}
