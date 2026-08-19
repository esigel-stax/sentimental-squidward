# The structured-output bug, and what it turned out to be

## Symptom

`run.py` crashed in `group_source` with a pydantic validation error:

```
ValidationError: 1 validation error for SourceDigest
groups
  Field required [type=missing,
   input_value={'parameters': '{"groups"...19, 20, 21, 25, 27]}]}'}, input_type=dict]
```

The model's answer was correct. It just arrived wrapped in `{"parameters": "<json string>"}`
instead of as `{"groups": [...]}`. It only started after switching the grouping
model from Opus 5 to Sonnet 5 — the same code had worked the run before.

## Root cause

litellm has two ways to satisfy `response_format` on Anthropic:

1. **Native** — Anthropic's own `output_format` parameter. Reliable, returns the
   object directly.
2. **Legacy emulation** — declare a synthetic tool called `json_tool_call` whose
   input schema is your schema, force `tool_choice` to it, then convert the tool
   arguments back into message content.

Which one you get is decided in `litellm/llms/anthropic/chat/transformation.py`.
In **1.83.9** (the version installed here) that decision was a hardcoded
substring list, around line 1042:

```python
if any(substring in model for substring in {
    "sonnet-4.5", "sonnet-4-5", "opus-4.1", "opus-4-1",
    "opus-4.5", "opus-4-5", "opus-4.6", "opus-4-6",
    "opus-4.7", "opus-4-7", "sonnet-4.6", "sonnet-4-6",
    "sonnet_4.6", "sonnet_4_6",
}):
    optional_params["output_format"] = ...    # native
else:
    _tool = self.map_response_format_to_anthropic_tool(...)   # legacy
```

No `sonnet-5`, no `opus-5`, no `fable-5`. **The newest model family silently fell
through to the legacy path**, and the legacy path is where the envelope shapes
come from.

Verified without spending a token — this only inspects the outgoing params:

```python
from litellm.utils import get_optional_params
for model in ["claude-sonnet-4-5", "claude-sonnet-5"]:
    p = get_optional_params(model=model, custom_llm_provider="anthropic",
                            response_format={"type": "json_object"})
    print(model, "native:" , bool(p.get("output_format")))
```

On 1.83.9:

| model | path taken |
|---|---|
| `claude-sonnet-4-5` | `output_format` — native ✅ |
| `claude-opus-4-6` | `output_format` — native ✅ |
| `claude-sonnet-5` | `json_tool_call` — legacy ❌ |
| `claude-opus-5` | `json_tool_call` — legacy ❌ |

## It is already fixed upstream

On `main` (1.98.0) the substring list is gone, replaced by a registry lookup:

```python
if AnthropicConfig._supports_model_capability(
    model, "supports_native_structured_output", self._resolved_provider
):
```

and `model_prices_and_context_window.json` carries
`supports_native_structured_output: true` for `claude-sonnet-5` and
`claude-opus-5`. So a new model works the day its registry entry lands, instead
of waiting for someone to remember this function.

**The fix is to upgrade, not to file anything.**

```bash
pip3 install --user --upgrade litellm
```

Then re-run the probe above; both models should report native.

## Why this was worth chasing anyway

The failure was silent. No warning, no error, no log line — you simply got the
less reliable code path and only found out when something downstream parsed
strictly. A hand-maintained allowlist that gates a capability will always drift
behind the model catalogue; the upstream fix moves that knowledge to the one
place that already tracks it.

Squidward keeps `_unwrap` regardless (`squidward/analyze.py`). It costs nothing
and it means the pipeline survives whichever path a given model/version takes:

```python
ENVELOPE_KEYS = ("parameters", "arguments", "input", "properties",
                 "result", "response", "output")
```

Three response shapes have been observed in practice: the plain object, a
double-encoded JSON string, and the tool-call envelope. All three parse.

## If you did want to contribute to litellm

The workflow, for reference:

```bash
gh repo fork BerriAI/litellm --clone       # fork + clone
cd litellm && git checkout -b fix/your-thing
# edit, then run the targeted tests
poetry install && poetry run pytest tests/llm_translation -k anthropic
git commit -am "fix: ..." && git push -u origin fix/your-thing
gh pr create --fill
```

Their CI runs lint, type checks, and a large test matrix; PRs that touch a
provider transform are expected to add a case under `tests/llm_translation/`.
