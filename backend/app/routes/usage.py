import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from app.config import get_supabase_client

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def get_usage_stats(days: int = 7):
    """Get API usage statistics for the past N days.

    Returns daily breakdown by provider and caller, plus totals.
    """
    supabase = get_supabase_client()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    result = (
        supabase.table("api_usage")
        .select("provider, caller, status, result_count, created_at")
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .execute()
    )

    rows = result.data

    # Aggregate by day
    daily: dict[str, dict] = {}
    for row in rows:
        day = row["created_at"][:10]
        if day not in daily:
            daily[day] = {"total": 0, "serper": 0, "brave": 0, "success": 0, "error": 0, "by_caller": {}}

        daily[day]["total"] += 1
        daily[day][row["provider"]] = daily[day].get(row["provider"], 0) + 1

        if row["status"] == "success":
            daily[day]["success"] += 1
        else:
            daily[day]["error"] += 1

        caller = row["caller"]
        daily[day]["by_caller"][caller] = daily[day]["by_caller"].get(caller, 0) + 1

    # Sort by date descending
    daily_sorted = [
        {"date": day, **stats}
        for day, stats in sorted(daily.items(), reverse=True)
    ]

    # Totals
    total = len(rows)
    total_serper = sum(1 for r in rows if r["provider"] == "serper")
    total_brave = sum(1 for r in rows if r["provider"] == "brave")
    total_success = sum(1 for r in rows if r["status"] == "success")
    total_error = total - total_success

    return {
        "period_days": days,
        "total_queries": total,
        "by_provider": {"serper": total_serper, "brave": total_brave},
        "success": total_success,
        "errors": total_error,
        "daily": daily_sorted,
    }
