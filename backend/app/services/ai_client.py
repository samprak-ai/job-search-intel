"""AI provider client — route LLM completions to a configured provider.

Centralizes the completion call so the provider is a config decision (AI_PROVIDER
in env) instead of a hardcode in each service. The system prompt is model-agnostic
and both providers consume it verbatim. Default is OpenRouter (stealth/ox-alpha);
DeepSeek (OpenAI-compatible) is opt-in.

Interface: complete(model, system, user, max_tokens) -> str
           complete_with_usage(model, system, user, max_tokens) -> (str, usage_dict)
"""
import httpx

from app.config import get_settings


def provider() -> str:
    return (get_settings().ai_provider or "deepseek").lower().replace(" ", "")


def _flatten_system(system) -> str:
    """Reduce a system-blocks list to a single text string for the
    OpenAI-compatible chat endpoint. Plain strings pass through unchanged."""
    if isinstance(system, str):
        return system
    parts = []
    for b in system:
        if isinstance(b, dict):
            parts.append(b.get("text") or "")
        else:
            parts.append(str(b))
    return "\n\n".join(p for p in parts if p)


def complete_deepseek(model: str | None, system: str, user: str, max_tokens: int) -> str:
    text, _, _ = complete_deepseek_with_usage(model, system, user, max_tokens)
    return text


def _deepseek_model(model: str | None) -> str:
    """Map a caller-supplied Claude label to the configured DeepSeek model. The
    `model` arg is a semantic fallback label, not a provider id — a call site that
    says 'claude-sonnet-4-6' means 'the standard sonnet-weight completion', which
    DeepSeek serves with its configured model (default deepseek-chat)."""
    if model and not model.startswith("claude"):
        return model
    return get_settings().deepseek_model


def _openai_compatible_chat(
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    extra_body: dict | None = None,
) -> tuple[str, int, int]:
    """Shared OpenAI-compatible chat completion (DeepSeek, OpenRouter, ...)."""
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if extra_body:
        body.update(extra_body)
    resp = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=120.0,
    )
    if resp.status_code != 200:
        # Surface the provider's error payload — OpenRouter embeds rate-limit
        # and provider-error detail in the JSON body.
        raise RuntimeError(f"LLM HTTP {resp.status_code} from {base_url}: {resp.text[:300]}")
    data = resp.json()
    usage = data.get("usage") or {}
    return (
        data["choices"][0]["message"]["content"].strip(),
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )


def complete_deepseek_with_usage(model: str | None, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
    s = get_settings()
    return _openai_compatible_chat(
        base_url=s.deepseek_base_url,
        api_key=s.deepseek_api_key,
        # deepseek-v4-pro (and the flash/reasoner family) default to a
        # thinking/reasoning mode whose output lands in reasoning_content and
        # leaves content empty. Scoring + all structured gen must be a plain,
        # deterministic, non-reasoning completion (matching temperature=0), so
        # disable thinking explicitly. Harmless on non-thinking models.
        model=_deepseek_model(model),
        system=system,
        user=user,
        max_tokens=max_tokens,
        extra_body={"thinking": {"type": "disabled"}},
    )


def _openrouter_model(model: str | None) -> str:
    """Same semantic-label mapping as DeepSeek: 'claude-sonnet-4-6' means 'the
    standard sonnet-weight completion', served by the configured OpenRouter
    model (default stealth/ox-alpha)."""
    if model and not model.startswith("claude"):
        return model
    return get_settings().openrouter_model


def complete_openrouter(model: str | None, system: str, user: str, max_tokens: int) -> str:
    text, _, _ = complete_openrouter_with_usage(model, system, user, max_tokens)
    return text


def complete_openrouter_with_usage(model: str | None, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
    """OpenRouter (OpenAI-compatible). Reasoning is MANDATORY on this model
    (the endpoint rejects enabled:false) and reasoning + content share the
    max_tokens budget — so scale the budget up or big prompts die with empty
    content. 'exclude' keeps the visible output clean. temperature=0 holds."""
    s = get_settings()
    return _openai_compatible_chat(
        base_url=s.openrouter_base_url,
        api_key=s.openrouter_api_key,
        model=_openrouter_model(model),
        system=system,
        user=user,
        max_tokens=max(max_tokens * 3, 4000),
        extra_body={"reasoning": {"exclude": True}},
    )


def complete(model: str | None, system, user: str, max_tokens: int = 1024) -> str:
    """Route a completion to the configured provider (deepseek default,
    openrouter opt-in). `model` is a fallback label; each provider applies its
    own default when None.

    `system` accepts either a plain string or a system-blocks list — blocks get
    flattened to text since the chat endpoint takes a single system string.
    """
    p = provider()
    if p == "openrouter":
        return complete_openrouter(model, _flatten_system(system), user, max_tokens)
    return complete_deepseek(model, _flatten_system(system), user, max_tokens)


def complete_with_usage(model: str | None, system, user: str, max_tokens: int = 1024) -> tuple[str, dict]:
    """Like complete() but also returns {input_tokens, output_tokens} for cost
    reporting (0s when the provider doesn't report usage)."""
    p = provider()
    if p == "openrouter":
        text, inp, out = complete_openrouter_with_usage(
            model, _flatten_system(system), user, max_tokens
        )
        return text, {"input_tokens": inp, "output_tokens": out}
    text, inp, out = complete_deepseek_with_usage(
        model, _flatten_system(system), user, max_tokens
    )
    return text, {"input_tokens": inp, "output_tokens": out}