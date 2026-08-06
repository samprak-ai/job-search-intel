"""AI provider client — route scoring/LLM completions to a configured provider.

Centralizes the completion call so the provider is a config decision (AI_PROVIDER
in env) instead of a hardcode in each service. Scorings only once; the system
prompt is model-agnostic and both providers consume it verbatim. Default stays
Anthropic (claude-sonnet-4-6); DeepSeek (OpenAI-compatible) is opt-in.

Interface: complete(model, system, user, max_tokens) -> str
"""
import httpx

from app.config import get_settings

_DEFAULT_CLAUDE = "claude-sonnet-4-6"


def provider() -> str:
    return (get_settings().ai_provider or "anthropic").lower().replace(" ", "")


def _call_anthropic(model: str | None, system: str, user: str, max_tokens: int) -> str:
    import anthropic

    s = get_settings()
    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    message = client.messages.create(
        model=model or _DEFAULT_CLAUDE,
        max_tokens=max_tokens,
        # Scoring is a grading task — it must be reproducible. Default temperature
        # (1.0) injects ±several points of run-to-run noise, enough to flip a role
        # across the Good/Strong boundary. temperature=0 makes the same JD score
        # the same number every time. (L26)
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text.strip()


def complete_deepseek(model: str | None, system: str, user: str, max_tokens: int) -> str:
    s = get_settings()
    resp = httpx.post(
        f"{s.deepseek_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {s.deepseek_api_key}"},
        json={
            "model": model or s.deepseek_model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def complete(model: str | None, system: str, user: str, max_tokens: int = 1024) -> str:
    """Route a completion to the configured provider. `model` is a fallback label
    for two-provider parity; each provider applies its own default when None."""
    if provider() == "deepseek":
        return complete_deepseek(model, system, user, max_tokens)
    return _call_anthropic(model, system, user, max_tokens)