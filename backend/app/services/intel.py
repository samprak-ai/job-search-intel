import asyncio
import json
import logging

import anthropic

from app.config import get_settings, get_supabase_client
from app.services.web_search import web_search

logger = logging.getLogger(__name__)

INTEL_SYSTEM_PROMPT = """You are an interview preparation research assistant. You analyze search results about a company's interview process and summarize them into actionable interview intelligence.

Given search results about a company's interview process for a specific role type, extract and synthesize:

1. interview_structure: A concise description of the interview process (number of rounds, format, timeline)
2. question_themes: Common question topics and themes (behavioral, technical, case study, etc.)
3. emphasis_areas: What the company cares about most when evaluating candidates
4. culture_signals: Company culture indicators, values, and what they look for in terms of fit

Respond with ONLY valid JSON in this exact format, no other text:
{
  "interview_structure": "Description of interview rounds and format",
  "question_themes": ["theme 1", "theme 2", "theme 3"],
  "emphasis_areas": ["area 1", "area 2", "area 3"],
  "culture_signals": ["signal 1", "signal 2", "signal 3"]
}"""


def build_intel_queries(company: str, role_type: str) -> list[str]:
    """Build Brave Search queries for interview intel."""
    return [
        f'"{company}" "{role_type}" interview questions reddit',
        f'"{company}" interview process site:levels.fyi',
        f'"{company}" "{role_type}" interview experience',
        f'"{company}" how we hire',
    ]


def build_intel_message(company: str, role_type: str, search_results: list[dict]) -> str:
    """Build the user message with search results for Claude."""
    results_text = ""
    for i, result in enumerate(search_results, 1):
        title = result.get("title", "")
        description = result.get("description", "")
        url = result.get("url", "")
        results_text += f"\n### Result {i}\n**Title:** {title}\n**URL:** {url}\n**Snippet:** {description}\n"

    return f"""## Interview Intel Request
**Company:** {company}
**Role Type:** {role_type}

## Search Results ({len(search_results)} results)
{results_text}

Based on these search results, synthesize interview intelligence for {role_type} roles at {company}. Focus on actionable preparation guidance."""


async def fetch_intel(company: str, role_type: str) -> dict:
    """Fetch and synthesize interview intel for a company/role type."""
    settings = get_settings()
    supabase = get_supabase_client()

    # Check if we already have recent intel for this combo
    existing = (
        supabase.table("interview_intel")
        .select("*")
        .eq("company", company)
        .eq("role_type", role_type)
        .execute()
    )
    if existing.data:
        logger.info(f"Found existing intel for {company} / {role_type}")
        record = existing.data[0]
        return {
            "company": company,
            "role_type": role_type,
            "cached": True,
            "interview_structure": record["interview_structure"],
            "question_themes": record["question_themes"],
            "emphasis_areas": record["emphasis_areas"],
            "culture_signals": record["culture_signals"],
        }

    # Run multiple search queries and collect results
    queries = build_intel_queries(company, role_type)
    all_results = []
    seen_urls = set()

    for query in queries:
        results = await web_search(
            query,
            serper_api_key=settings.serper_api_key,
            brave_api_key=settings.brave_api_key,
            count=10,
            caller="intel",
        )
        for r in results:
            url = r.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                all_results.append(r)
        await asyncio.sleep(1.0)  # Rate limit between queries

    if not all_results:
        return {
            "company": company,
            "role_type": role_type,
            "cached": False,
            "interview_structure": "No interview data found",
            "question_themes": [],
            "emphasis_areas": [],
            "culture_signals": [],
        }

    logger.info(f"Collected {len(all_results)} search results for {company} / {role_type}")

    # Send to Claude for summarization
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=INTEL_SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": build_intel_message(company, role_type, all_results)}
        ],
    )

    # Parse response (strip markdown fences if present)
    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        response_text = response_text.rsplit("```", 1)[0]
        response_text = response_text.strip()

    try:
        intel_data = json.loads(response_text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse Claude intel response: {response_text[:200]}")
        raise ValueError("Claude returned invalid JSON for interview intel")

    # Build source references
    raw_sources = [
        {"url": r.get("url", ""), "title": r.get("title", "")}
        for r in all_results[:20]  # Cap stored sources
    ]

    # Upsert into interview_intel table (unique on company + role_type)
    intel_record = {
        "company": company,
        "role_type": role_type,
        "interview_structure": intel_data.get("interview_structure", ""),
        "question_themes": intel_data.get("question_themes", []),
        "emphasis_areas": intel_data.get("emphasis_areas", []),
        "culture_signals": intel_data.get("culture_signals", []),
        "raw_sources": raw_sources,
    }
    supabase.table("interview_intel").upsert(
        intel_record, on_conflict="company,role_type"
    ).execute()
    logger.info(f"Stored intel for {company} / {role_type}")

    return {
        "company": company,
        "role_type": role_type,
        "cached": False,
        **intel_data,
    }
