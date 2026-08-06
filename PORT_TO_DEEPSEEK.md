# PORT_TO_DEEPSEEK.md — Migrate an app to DeepSeek

This is the field-tested playbook from the **job-search-intel** migration (July-Aug 2026).
It's a proven pattern, not a fresh design: copy the abstraction, wire every call
site through it, pin anything that shouldn't follow `AI_PROVIDER`, and guard the
wiring with a deterministic selfcheck so the swap can never silently regress.

Working reference implementation: `backend/app/services/ai_client.py` in this repo.

---

## 0. Decide before you start

- **Is a swap even worth it?** DeepSeek is ~8x cheaper than Claude Sonnet 4.6 on
  token rates ($0.435/$0.87 vs $3/$15 per 1M). The win is real but small at low
  volume. Do the math first (see §5).
- **Which tier?** `deepseek-v4-flash` ($0.14/$0.28) is the cheap tier;
  `deepseek-v4-pro` ($0.435/$0.87) is the capability tier and the closer analogue
  to Sonnet. Start on pro for anything that matters. (`deepseek-chat` is the
  DEPRECATED flash alias — retired 2026-07-24 — do not use it.)
- **Who is exempt?** Anything small, proven, and cheap that feeds a decision loop
  (a classifier, a fast extractor) should probably STAY on Claude. It saves
  ~nothing to swap it and risks the thing you already trust.

---

## 1. Create the provider client

One file. No provider SDK imported at module top level (import lazily so the
other provider's SDK is never required). Core shape:

```python
# services/ai_client.py
import httpx
from app.config import get_settings

_DEFAULT_CLAUDE = "claude-sonnet-4-6"

def provider() -> str:
    return (get_settings().ai_provider or "anthropic").lower().replace(" ", "")

def complete(model, system, user, max_tokens=1024) -> str:
    """model is a SEMANTIC label (e.g. 'claude-sonnet-4-6' = 'standard weight'),
    not a provider id. Each provider maps it to its own model."""
    if provider() == "deepseek":
        return complete_deepseek(model, _flatten_system(system), user, max_tokens)
    return _call_anthropic(model, system, user, max_tokens)

def complete_with_usage(model, system, user, max_tokens=1024) -> tuple[str, dict]:
    """Same, but returns {input_tokens, output_tokens} for cost reporting."""
    ...
```

### The three traps that cost real debugging time (all hit in the source migration)

1. **DeepSeek `v4-pro` is a thinking model by default.** Its reasoning goes to
   `reasoning_content` and `content` comes back EMPTY. You must send
   `"thinking": {"type": "disabled"}` on every call or your JSON parser breaks.
   (This silently broke quick-apply and the A/B harness until fixed.)
   ```python
   json={
       "model": _deepseek_model(model),
       "temperature": 0,
       "max_tokens": max_tokens,
       "thinking": {"type": "disabled"},   # <- mandatory for v4-pro
       "messages": [...],
   }
   ```
2. **`model` strings are provider-specific.** Existing call sites say
   `"claude-sonnet-4-6"`. DeepSeek rejects that id with a 400. Map any
   `claude-*` label to the configured DeepSeek model:
   ```python
   def _deepseek_model(model):
       if model and not model.startswith("claude"):
           return model
       return get_settings().deepseek_model
   ```
3. **Anthropic `system` blocks vs DeepSeek string.** Claude accepts a `system`
   blocks list (with `cache_control`). The OpenAI-compatible endpoint takes a
   single string. Flatten blocks for DeepSeek, pass them verbatim for Claude
   (preserves prompt caching). `_flatten_system()` in the source handles both.

### Config keys (mirror source `config.py`)

```
ai_provider        = env("AI_PROVIDER", "anthropic")     # or "deepseek"
deepseek_api_key   = env("DEEPSEEK_API_KEY")
deepseek_model     = env("DEEPSEEK_MODEL", "deepseek-v4-pro")
deepseek_base_url  = env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
```

---

## 2. Wire every call site through the client

Find all direct SDK calls (in the source migration they were all the same shape):

```
anthropic.Anthropic(...).messages.create(
    model="claude-sonnet-4-6", max_tokens=..., system=..., messages=[...])
```

Replace each with:

```python
from app.services.ai_client import complete
text = complete("claude-sonnet-4-6", SYSTEM_PROMPT, user_msg, max_tokens=2048)
```

Mechanical rules:
- Use `complete_with_usage` only where you report token cost (quick-apply did).
- `system` may stay a blocks list; the client normalizes per provider.
- Keep `temperature=0` semantics — it lives in the client now, not the call site.
- Do NOT leave a half-migrated call site. That's the silent-regression trap.

**Exempt services stay as-is** (direct Anthropic SDK call) and get a guard (§4).

---

## 3. Env + deploy (Railway/Vercel pattern)

- Local `.env`: add `AI_PROVIDER`, `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`.
- Prod (Railway): set the same three as **Variables**. Saving a var triggers a
  redeploy; the code change is what ships `thinking: disabled`.
- The config default applies only when the env var is absent — set
  `DEEPSEEK_MODEL` explicitly on prod rather than trusting the default.
- Verify the deployed app actually uses DeepSeek by triggering the real work
  (a score / a generation) and confirming a clean result, not just `/health`.
  A thinking-mode pro response returns 200 but empty content — a green health
  check proves nothing about the swap.

---

## 4. Guard the wiring (selfcheck / LEARNINGS pattern)

The provider switch is a runtime config decision. If any service bypasses the
client, `AI_PROVIDER` is silently ignored and a "we're on DeepSeek" assumption
becomes false. Add a deterministic check that FAILS on the bad state:

```python
@check("L31-inference-routes-through-ai-client")
def _l31():
    problems = []
    client = read("app/services/ai_client.py")
    if "def complete(" not in client: problems.append(...)
    if "deepseek" not in client or "anthropic" not in client: problems.append(...)
    for module in ("service_a.py", "service_b.py", ...):  # every migrated module
        src = read(f"app/services/{module}")
        if "anthropic.Anthropic(" in src or "client.messages.create(" in src:
            problems.append(f"{module}: must route through ai_client.complete")
    return problems
```

And one for the pinned exception — it must NOT route through the client:

```python
@check("L32-classifier-stays-on-claude")
def _l32():
    problems = []
    src = read("app/services/classifier.py")
    if "anthropic.Anthropic(" not in src: problems.append("must call Anthropic SDK directly")
    ai = read("app/services/ai_client.py")
    if "classify" in ai: problems.append("client must not special-case the classifier")
    return problems
```

Commit the guard + a `LEARNINGS.md` entry together. Confirm it FAILS on the bad
state and PASSES on the fix before committing.

---

## 5. Calibration: do the math, then A/B the behavior

**Cost per N calls** (measured real tokens: ~5,960 input + ~490 output per
scoring call):

| | Claude Sonnet 4.6 | DeepSeek V4 Flash | DeepSeek V4 Pro |
|---|---|---|---|
| Input $/1M | $3.00 | $0.14 | $0.435 |
| Output $/1M | $15.00 | $0.28 | $0.87 |
| 100 calls | ~$2.53 | ~$0.10 | ~$0.30 |
| 1,000 calls | ~$25.30 | ~$1.00 | ~$3.00 |

**Behavioral A/B before committing to the swap** (mirror `scripts/ab_score.py`):
run the SAME prompt through both providers on representative inputs and compare:
- **Correctness** — same JSON shape, same judgment calls.
- **Band usage** — DeepSeek Flash compresses scores into the 80-89 band
  (underrates the 90+ tail). **Pro does NOT** (source: 94-95 where flash gave 84).
  If your app has tier boundaries, check whether the target tier uses all bands.
- **Determinism** — run twice; `temperature=0` should give identical results on
  both. If not, treat run-to-run noise as a scoring bug.
- **Voice/quality** — for generative output (emails, prose), eyeball real drafts.
  Grounding + no model-isms beats token price.

Watch real outcomes after the swap (the source app logs predicted-vs-actual and
re-tunes scoring adjustments). A band-adjust layer is the fallback if the target
tier's compression shows up in real results.

---

## Quick start checklist

- [ ] `services/ai_client.py` exists, dispatches on `AI_PROVIDER`, `temperature=0`
- [ ] `thinking: {"type": "disabled"}` on every DeepSeek call
- [ ] `_deepseek_model()` maps `claude-*` labels → configured model
- [ ] `_flatten_system()` handles blocks → string for DeepSeek
- [ ] All migrated call sites use `complete()` / `complete_with_usage()`
- [ ] Exempt services still call Anthropic directly (by design)
- [ ] Config keys added; local `.env` + prod vars set; prod redeployed
- [ ] L31-style guard covers every migrated module; L32-style guard pins the exempt service
- [ ] A/B ran on representative inputs; band behavior + determinism checked
- [ ] `LEARNINGS.md` entry committed with the guards
