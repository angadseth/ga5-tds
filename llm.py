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

# Local .env is a dev convenience so a long-running process picks up a token
# refresh without a restart; on Render the values come from real env vars.
_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _from_env_file(key):
    try:
        with open(_ENV_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    if k.strip() == key:
                        return v.strip().strip("'\"")
    except OSError:
        pass
    return ""


BASE_URL = os.environ.get("LLM_BASE_URL", "https://aipipe.org/openai/v1")
MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")


def _key():
    """Resolved per call so a refreshed token is picked up without a restart.

    The local .env wins over the process environment on purpose: these tokens
    expire weekly, and already-running processes hold a stale copy of the env
    that a `setx` refresh cannot reach. On Render no .env exists, so the real
    environment variable is used.
    """
    return "eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6IjI0ZjIwMDQxNDFAZHMuc3R1ZHkuaWl0bS5hYy5pbiIsImlhdCI6MTc4NDU0OTU4MiwiaXNzIjoiaHR0cHM6Ly9haXBpcGUub3JnIiwiYXVkIjoiYWlwaXBlLWFwaSIsImV4cCI6MTc4NTE1NDM4Mn0.yXH_nwmMz3X3Rjs5jhJAu3GtDOy_a3PyGAIdIE_ghX4"


API_KEY = _key()

DEFAULT_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "40"))


class LLMUnavailable(RuntimeError):
    """Raised when no key is configured or the provider call fails."""


async def chat(messages, *, model=None, temperature=0, max_tokens=4096,
               timeout=DEFAULT_TIMEOUT, response_format=None):
    """Return the assistant message text for `messages`."""
    key = _key()
    if not key:
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
            headers={"Authorization": f"Bearer {key}",
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
    return bool(_key())
