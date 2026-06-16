import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import (
    application_outcomes,
    application_packages,
    application_updates,
    detected_gaps,
    discover,
    forge,
    freshness,
    intel,
    quick_apply,
    reflect,
    resume_tailor,
    review,
    roles,
    score,
    scoring_adjustments,
    usage,
)

app = FastAPI(title="Job Search Intelligence", version="0.1.0")

# CORS: allow localhost for dev + any configured FRONTEND_URL for production
_cors_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_frontend_url = os.environ.get("FRONTEND_URL", "")
if _frontend_url:
    _cors_origins.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(discover.router, prefix="/discover", tags=["discovery"])
app.include_router(score.router, prefix="/score", tags=["scoring"])
app.include_router(intel.router, prefix="/intel", tags=["intel"])
app.include_router(roles.router, prefix="/roles", tags=["roles"])
app.include_router(forge.router, prefix="/forge", tags=["forge"])
app.include_router(usage.router, prefix="/usage", tags=["usage"])
app.include_router(resume_tailor.router, prefix="/resume-tailor", tags=["resume-tailor"])
app.include_router(review.router, prefix="/review", tags=["review"])
app.include_router(quick_apply.router, prefix="/quick-apply", tags=["quick-apply"])
app.include_router(freshness.router, prefix="/freshness", tags=["freshness"])
app.include_router(application_packages.router, prefix="/application-packages", tags=["application-packages"])
app.include_router(application_outcomes.router, prefix="/application-outcomes", tags=["application-outcomes"])
app.include_router(application_updates.router, prefix="/application-updates", tags=["application-updates"])
app.include_router(detected_gaps.router, prefix="/detected-gaps", tags=["detected-gaps"])
app.include_router(reflect.router, prefix="/reflect", tags=["reflect"])
app.include_router(scoring_adjustments.router, prefix="/scoring-adjustments", tags=["scoring-adjustments"])


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/companies")
async def list_companies():
    from app.config import load_companies
    return {"companies": load_companies()}
