"""AI provider client — route LLM completions to a configured provider.

Centralizes the completion call so the provider is a config decision (AI_PROVIDER
in env) instead of a hardcode in each service. The system prompt is model-agnostic
and both providers consume it verbatim. Default stays Anthropic
(claude-sonnet-4-6); DeepSeek (OpenAI-compatible) is opt-in.

Interface: complete(model, system, user, max_tokens) -> str
           complete_with_usage(model, system, user, max_tokens) -> (str, usage_dict)
"""
import httpx

from app.config import get_settings

_DEFAULT_CLAUDE = "claude-sonnet-4-6"


def provider() -> str:
    return (get_settings().ai_provider or "anthropic").lower().replace(" ", "")


def _flatten_system(system) -> str:
    """Reduce an Anthropic system-blocks list to a single text string for
    OpenAI-compatible providers. Plain strings pass through unchanged."""
    if isinstance(system, str):
        return system
    parts = []
    for b in system:
        if isinstance(b, dict):
            parts.append(b.get("text") or "")
        else:
            parts.append(str(b))
    return "\n\n".join(p for p in parts if p)


def _call_anthropic(model: str | None, system, user: str, max_tokens: int) -> str:
    text, _ = _call_anthropic_with_usage(model, system, user, max_tokens)
    return text


def _call_anthropic_with_usage(model: str | None, system, user: str, max_tokens: int) -> tuple[str, dict]:
    import anthropic

    s = get_settings()
    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    message = client.messages.create(
        model=model or _DEFAULT_CLAUDE,
        max_tokens=max_tokens,
        # Grading + structured generation must be reproducible. Default temperature
        # (1.0) injects ±several points of run-to-run noise, enough to flip a role
        # across the Good/Strong boundary. temperature=0 makes the same input
        # produce the same result every time. (L26)
        temperature=0,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    usage = {
        "input_tokens": getattr(message.usage, "input_tokens", 0),
        "output_tokens": getattr(message.usage, "output_tokens", 0),
    }
    return message.content[0].text.strip(), usage


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


def complete_deepseek_with_usage(model: str | None, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
    s = get_settings()
    resp = httpx.post(
        f"{s.deepseek_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {s.deepseek_api_key}"},
        json={
            "model": _deepseek_model(model),
            "temperature": 0,
            "max_tokens": max_tokens,
            # deepseek-v4-pro (and the flash/reasoner family) default to a
            # thinking/reasoning mode whose output lands in reasoning_content and
            # leaves content empty. Scoring + all structured gen must be a plain,
            # deterministic, non-reasoning completion (matching temperature=0), so
            # disable thinking explicitly. Harmless on non-thinking models.
            "thinking": {"type": "disabled"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage") or {}
    return (
        data["choices"][0]["message"]["content"].strip(),
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
    )


def complete(model: str | None, system, user: str, max_tokens: int = 1024) -> str:
    """Route a completion to the configured provider. `model` is a fallback label
    for two-provider parity; each provider applies its own default when None.

    `system` accepts either a plain string or an Anthropic system-blocks list
    (e.g. a persona block carrying cache_control). Anthropic gets the blocks
    verbatim (preserving prompt caching); DeepSeek gets them flattened to text
    since the OpenAI-compatible endpoint takes a single system string.
    """
    if provider() == "deepseek":
        return complete_deepseek(model, _flatten_system(system), user, max_tokens)
    return _call_anthropic(model, system, user, max_tokens)


def complete_with_usage(model: str | None, system, user: str, max_tokens: int = 1024) -> tuple[str, dict]:
    """Like complete() but also returns {input_tokens, output_tokens} for cost
    reporting (0s when the provider doesn't report usage)."""
    if provider() == "deepseek":
        text, inp, out = complete_deepseek_with_usage(
            model, _flatten_system(system), user, max_tokens
        )
        return text, {"input_tokens": inp, "output_tokens": out}
    return _call_anthropic_with_usage(model, system, user, max_tokens)