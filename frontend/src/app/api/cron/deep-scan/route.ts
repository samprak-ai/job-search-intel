import { NextRequest, NextResponse } from "next/server";

/**
 * Weekly deep-scan cron job — runs a more aggressive freshness pass than
 * the daily /cron route. Force-rechecks every role (clears ATS listing cache),
 * applies content-signal checks on non-ATS URLs, and deletes stale roles +
 * their scores.
 *
 * Scheduled in vercel.json: Sunday 15:00 UTC (1 hour after the daily cron's
 * 14:00 UTC discovery, so they don't overlap).
 *
 * Forwards to FastAPI backend's /discover/deep-scan endpoint.
 *
 * Required env vars (set in Vercel project settings):
 *   BACKEND_URL  — e.g. https://your-railway-app.up.railway.app
 *   CRON_SECRET  — shared secret matching the backend's CRON_SECRET
 */
export async function GET(request: NextRequest) {
  const authHeader = request.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;

  if (!cronSecret) {
    return NextResponse.json(
      { error: "CRON_SECRET not configured" },
      { status: 500 }
    );
  }

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
    const res = await fetch(`${backendUrl}/discover/deep-scan`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${cronSecret}`,
        "Content-Type": "application/json",
      },
      // Deep scan can take longer than daily cron — allow 10 minutes
      signal: AbortSignal.timeout(600_000),
    });

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: "Backend deep-scan failed", detail: data },
        { status: res.status }
      );
    }

    return NextResponse.json({
      status: "completed",
      trigger: "vercel_cron_weekly_deepscan",
      ...data,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json(
      { error: "Deep-scan request failed", detail: message },
      { status: 500 }
    );
  }
}
