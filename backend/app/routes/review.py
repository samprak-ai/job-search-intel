"""HTTP routes for the Application Reviewer.

Company-agnostic QC for any drafted application text. Complements the
Anthropic-only agents/critic pipeline.

Endpoints:
  POST /review        — review a single piece of text
  POST /review/batch  — review several drafts in one call
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.reviewer import review

logger = logging.getLogger(__name__)
router = APIRouter()


class ReviewIn(BaseModel):
    text: str = Field(..., description="The drafted application text to review.")
    company: str | None = Field(None, description="e.g. Anthropic, OpenAI, Google DeepMind, Amazon")
    artifact_type: str | None = Field(
        None, description="why | additional_info | cover_letter | why_role | relevant_skills | performance_history | work_contribution"
    )
    jd: str | None = Field(None, description="Role JD or title, for the alignment grader.")
    require_contact: bool = False
    use_llm: bool = True


class BatchIn(BaseModel):
    items: list[ReviewIn]


@router.post("")
async def review_text(body: ReviewIn):
    """Review one draft. Returns the structured report with a verdict
    (pass | review | block). Groundedness failures are hard blocks."""
    return review(
        body.text,
        company=body.company,
        artifact_type=body.artifact_type,
        jd=body.jd,
        require_contact=body.require_contact,
        use_llm=body.use_llm,
    )


@router.post("/batch")
async def review_batch(body: BatchIn):
    """Review several drafts. Returns one report per item, plus a summary count."""
    reports = [
        review(it.text, company=it.company, artifact_type=it.artifact_type,
               jd=it.jd, require_contact=it.require_contact, use_llm=it.use_llm)
        for it in body.items
    ]
    summary = {"pass": 0, "review": 0, "block": 0}
    for r in reports:
        summary[r["verdict"]] = summary.get(r["verdict"], 0) + 1
    return {"summary": summary, "reports": reports}
