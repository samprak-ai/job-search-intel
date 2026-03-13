import io
import json
import logging
import os
import subprocess

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.config import get_supabase_client, load_profile

from app.services.resume_tailor import generate_resume_tailoring

logger = logging.getLogger(__name__)
router = APIRouter()

# Path to the Node.js resume generator script
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
GENERATOR_SCRIPT = os.path.join(SCRIPTS_DIR, "generate_resume.js")


@router.post("/{role_id}")
async def create_resume_tailoring(role_id: str):
    """Generate resume tailoring advice for a specific role."""
    result = await generate_resume_tailoring(role_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return result


@router.get("/{role_id}/download")
async def download_tailored_resume(role_id: str):
    """Download a tailored .docx resume for a specific role."""
    supabase = get_supabase_client()

    # Fetch tailoring data
    tailoring_result = (
        supabase.table("resume_tailors")
        .select("tailoring")
        .eq("role_id", role_id)
        .execute()
    )
    if not tailoring_result.data:
        raise HTTPException(
            status_code=404,
            detail="No tailoring found. Generate resume tailoring first.",
        )

    tailoring = tailoring_result.data[0]["tailoring"]

    # Fetch role metadata for filename
    role_result = (
        supabase.table("roles")
        .select("company, title")
        .eq("id", role_id)
        .execute()
    )
    role = role_result.data[0] if role_result.data else {}
    company = role.get("company", "Company").replace(" ", "_")

    # Load profile
    profile = load_profile()

    # Build input JSON for the Node.js script
    input_data = json.dumps({
        "profile": profile,
        "tailoring": tailoring,
        "company": role.get("company", ""),
        "title": role.get("title", ""),
    })

    # Call the Node.js generator script
    try:
        result = subprocess.run(
            ["node", GENERATOR_SCRIPT],
            input=input_data.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Resume generation timed out")
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="Node.js not found. Required for resume generation.",
        )

    if result.returncode != 0:
        error_msg = result.stderr.decode("utf-8", errors="replace")
        logger.error(f"Resume generation failed: {error_msg}")
        raise HTTPException(
            status_code=500,
            detail=f"Resume generation failed: {error_msg[:200]}",
        )

    docx_bytes = result.stdout
    if not docx_bytes:
        raise HTTPException(status_code=500, detail="Resume generation produced empty output")

    filename = f"Sam_Prakash_Resume_{company}.docx"

    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{role_id}")
async def get_resume_tailoring(role_id: str):
    """Retrieve existing resume tailoring for a role."""
    supabase = get_supabase_client()

    result = (
        supabase.table("resume_tailors")
        .select("*")
        .eq("role_id", role_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="No tailoring found for this role")

    return result.data[0]
