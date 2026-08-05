"""
Shared text-generation client for all UBW agents, routed through kie.ai.

Model chain (first one that answers wins):
  1. claude-sonnet-5   — kie.ai Claude market (Anthropic Messages protocol).
                         Currently down on kie.ai's side ("commonLLM ... 403",
                         ticket open since 2026-08-05); kept first so the agent
                         upgrades itself the moment kie.ai fixes it.
  2. gpt-5-6-sol       — kie.ai Codex/Responses market. Verified working
                         2026-08-05 (~0.2 credits per caption-sized call).

Usage:
    from kie_llm import generate_text
    text, usage = generate_text(user_prompt, system=..., max_tokens=1024)
    # usage = {"input_tokens": int, "output_tokens": int, "model": str}
"""

import os
import sys

import anthropic
import requests

KIE_CLAUDE_BASE_URL = "https://api.kie.ai/claude"
KIE_RESPONSES_URL   = "https://api.kie.ai/codex/v1/responses"

CLAUDE_MODEL = "claude-sonnet-5"
GPT_MODEL    = "gpt-5-6-sol"

REQUEST_TIMEOUT = 180  # seconds


def _api_key() -> str:
    key = os.environ.get("KIE_API_KEY", "")
    if not key:
        raise RuntimeError("KIE_API_KEY not set")
    return key


def _try_claude(user_prompt: str, system: str | None, max_tokens: int):
    client = anthropic.Anthropic(base_url=KIE_CLAUDE_BASE_URL, auth_token=_api_key())
    kwargs = dict(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": user_prompt}],
    )
    if system:
        kwargs["system"] = system
    message = client.messages.create(**kwargs)
    text = message.content[0].text.strip()
    usage = {
        "input_tokens":  message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "model": CLAUDE_MODEL,
    }
    return text, usage


def _try_gpt(user_prompt: str, system: str | None, max_tokens: int):
    payload = {
        "model": GPT_MODEL,
        "input": [{"role": "user", "content": user_prompt}],
        "stream": False,
        "max_output_tokens": max_tokens,  # accepted but not enforced by kie.ai
    }
    if system:
        # Without this, kie.ai injects a default "You are Codex" coding persona.
        payload["instructions"] = system
    resp = requests.post(
        KIE_RESPONSES_URL,
        json=payload,
        headers={"Authorization": f"Bearer {_api_key()}"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "completed" or data.get("error"):
        raise RuntimeError(f"kie.ai {GPT_MODEL} returned status={data.get('status')} "
                           f"error={data.get('error')}")
    text = "".join(
        c.get("text", "")
        for o in data.get("output", []) if o.get("type") == "message"
        for c in o.get("content", [])
    ).strip()
    if not text:
        raise RuntimeError(f"kie.ai {GPT_MODEL} returned an empty message")
    u = data.get("usage") or {}
    usage = {
        "input_tokens":  u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "model": GPT_MODEL,
    }
    return text, usage


def generate_text(user_prompt: str, system: str | None = None,
                  max_tokens: int = 1024) -> tuple[str, dict]:
    """Generate text via kie.ai, falling through the model chain.

    Raises the last error if every model in the chain fails — billing-related
    messages propagate so callers can trigger the credit alert email.
    """
    try:
        return _try_claude(user_prompt, system, max_tokens)
    except anthropic.APIStatusError as e:
        msg = str(e).lower()
        if "billing" in msg or "credit" in msg:
            raise  # out of kie.ai credits — falling back would fail too
        print(f"[kie_llm] {CLAUDE_MODEL} unavailable ({str(e)[:120]}) — "
              f"falling back to {GPT_MODEL}", file=sys.stderr)
    except anthropic.APIConnectionError as e:
        print(f"[kie_llm] {CLAUDE_MODEL} connection error ({str(e)[:120]}) — "
              f"falling back to {GPT_MODEL}", file=sys.stderr)
    return _try_gpt(user_prompt, system, max_tokens)


if __name__ == "__main__":
    text, usage = generate_text("Reply with exactly: OK", system="You are a test probe.")
    print(f"model={usage['model']} tokens={usage['input_tokens']}in/"
          f"{usage['output_tokens']}out\n{text}")
