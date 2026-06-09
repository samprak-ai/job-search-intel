import { NextRequest, NextResponse } from "next/server";

/**
 * Weekly cron job — triggers the reflection pass on the backend.
 *
 * Vercel Cron calls this route on schedule (see vercel.json). It forwards to
 * the FastAPI backend's /reflect/cron endpoint, which analyzes accumulated
 * application_outcomes + open detected_gaps and emails a review report.
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
    const res = await fetch(`${backendUrl}/reflect/cron`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${cronSecret}`,
        "Content-Type": "application/json",
      },
      signal: AbortSignal.timeout(120_000),
    });

    const data = await res.json();

    if (!res.ok) {
      return NextResponse.json(
        { error: "Backend reflection failed", detail: data },
        { status: res.status }
      );
    }

    return NextResponse.json({
      status: "completed",
      trigger: "vercel_cron",
      ...data,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unknown error";
    return NextResponse.json(
      { error: "Reflection cron request failed", detail: message },
      { status: 500 }
    );
  }
}
