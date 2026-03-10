import logging

from fastapi import APIRouter, HTTPException

from app.services.intel import fetch_intel

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{company}")
async def fetch_interview_intel(company: str, role_type: str = "AI Solutions Engineer"):
    """Fetch interview intel for a company and role type.

    Runs Brave Search queries targeting Reddit, Levels.fyi, and company
    career pages, then summarizes via Claude API into a structured
    interview framework.
    """
    try:
        result = await fetch_intel(company, role_type)
        return {"status": "completed", **result}
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Intel fetch failed for {company}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
