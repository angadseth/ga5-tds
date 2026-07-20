"""Single shared LLM client for the GA5 agent questions (Q9, Q10, Q11).

Provider-agnostic on purpose: the exam gives no marks for provider or token
counts, so everything routes through one OpenAI-compatible chat-completions
call whose base URL, key and model come from the environment. Swapping
provider is an env change, not a code change.
"""
import json
import os
import re

import httpx

BASE_URL = os.environ.get("LLM_BASE_URL", "https://aipipe.org/openai/v1")
API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("AIPIPE_TOKEN", "")
MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")

DEFAULT_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "40"))


class LLMUnavailable(RuntimeError):
    """Raised when no key is configured or the provider call fails."""


async def chat(messages, *, model=None, temperature=0, max_tokens=4096,
               timeout=DEFAULT_TIMEOUT, response_format=None):
    """Return the assistant message text for `messages`."""
    if not API_KEY:
        raise LLMUnavailable("no LLM_API_KEY / AIPIPE_TOKEN configured")

    payload = {
        "model": model or MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}",
                     "Content-Type": "application/json"},
            json=payload,
        )
    if resp.status_code >= 400:
        raise LLMUnavailable(f"{resp.status_code}: {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"]


async def chat_json(messages, **kwargs):
    """Same as `chat` but parses the reply as JSON, tolerating code fences."""
    kwargs.setdefault("response_format", {"type": "json_object"})
    try:
        text = await chat(messages, **kwargs)
    except LLMUnavailable:
        # Some providers reject response_format; retry once without it.
        kwargs.pop("response_format", None)
        text = await chat(messages, **kwargs)
    return _loads(text)


def _loads(text):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i != -1] or [-1])
        end = max(text.rfind("}"), text.rfind("]"))
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def available() -> bool:
    return bool(API_KEY)
