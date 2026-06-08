"""Application package pipeline: Gate → Persona → Angles → Spec → Draft → Critic → Heal → Email.

A multi-stage agentic pipeline that turns an Anthropic Strong+ match into a
submit-ready package (resume.docx, cover_letter.docx, why_anthropic.md) emailed
to Sam for review or auto-send.

Public API:
    from app.services.agents.pipeline import run_pipeline
"""
