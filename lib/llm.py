"""
Thin LLM wrapper — the only place provider SDK calls may appear.

Exposes one function ``complete(agent_name, messages, **opts)`` that
resolves the model for the given agent from config, applies timeout and
retry, and returns the response text.

All agents call this module; no agent imports a provider SDK directly.
See Design Doc §7 and AGENTS.md ("All LLM calls go through lib/llm.py").
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Optional

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()  # reads .env at project root

# Per-agent model mapping from env vars (see .env.example).
_AGENT_MODEL_KEYS: dict[str, str] = {
    "planner": "PLANNER_MODEL",
    "designer": "DESIGNER_MODEL",
    "engineer": "ENGINEER_MODEL",
    "integration": "INTEGRATION_MODEL",
    "qa": "QA_MODEL",
    "critic": "CRITIC_MODEL",
}

_DEFAULT_MODEL = "claude-3-5-sonnet-20241022"
try:
    _DEFAULT_TIMEOUT = max(1, int(os.getenv("LLM_TIMEOUT_SECONDS", "60") or "60"))
except ValueError:
    _DEFAULT_TIMEOUT = 60
_DEFAULT_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds; exponential backoff multiplier

# ---------------------------------------------------------------------------
# Fake / test provider registry
# ---------------------------------------------------------------------------
_fake_handler: Optional[Callable[..., str]] = None


def set_fake_llm_handler(handler: Optional[Callable[..., str]]) -> None:
    """Register (or clear) a fake handler for testing.

    When a handler is set, ``complete()`` delegates to it instead of making
    a real network call.  The handler signature must be::

        handler(agent_name: str, messages: list[dict], model: str, **opts) -> str
    """
    global _fake_handler
    _fake_handler = handler


def get_fake_llm_handler() -> Optional[Callable[..., str]]:
    """Return the currently registered fake handler, or None."""
    return _fake_handler


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------
def get_model_for_agent(agent_name: str) -> str:
    """Return the model string configured for *agent_name*."""
    env_key = _AGENT_MODEL_KEYS.get(agent_name)
    if env_key is None:
        raise ValueError(
            f"Unknown agent '{agent_name}'. "
            f"Valid agents: {sorted(_AGENT_MODEL_KEYS)}"
        )
    return os.getenv(env_key, _DEFAULT_MODEL)


# ---------------------------------------------------------------------------
# Core entrypoint
# ---------------------------------------------------------------------------
class LLMError(Exception):
    """Raised when the LLM call fails after all retries."""


def complete(
    agent_name: str,
    messages: list[dict[str, Any]],
    *,
    timeout: Optional[int] = None,
    max_retries: Optional[int] = None,
    **opts: Any,
) -> str:
    """Send *messages* to the model configured for *agent_name* and return
    the response text.

    Args:
        agent_name: One of the six agent names.
        messages: Chat-style message list ``[{"role": ..., "content": ...}]``.
        timeout: Per-call timeout in seconds (default from env).
        max_retries: Number of retries on transient failure (default 3).
        **opts: Extra keyword arguments forwarded to the provider call.

    Returns:
        The assistant's response as a plain string.

    Raises:
        LLMError: After all retries are exhausted.
        ValueError: For unknown agent names.
    """
    model = opts.pop("model", None) or get_model_for_agent(agent_name)
    timeout = timeout if timeout is not None else _DEFAULT_TIMEOUT
    max_retries = max_retries if max_retries is not None else _DEFAULT_MAX_RETRIES

    # --- Fake handler (testing) ---
    if _fake_handler is not None:
        return _fake_handler(agent_name, messages, model=model, **opts)

    # --- Real provider call (placeholder for provider SDK integration) ---
    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            return _call_provider(model, messages, timeout=timeout, **opts)
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                backoff = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                time.sleep(backoff)

    raise LLMError(
        f"LLM call for agent '{agent_name}' (model={model}) failed "
        f"after {max_retries} retries: {last_error}"
    ) from last_error


# ---------------------------------------------------------------------------
# Provider isolation — swap implementation here when adding a new provider
# ---------------------------------------------------------------------------
def _call_provider(
    model: str,
    messages: list[dict[str, Any]],
    *,
    timeout: int,
    **opts: Any,
) -> str:
    """Call the underlying LLM provider.

    Supports Anthropic (Claude), OpenAI (GPT), Google (Gemini), and Groq via HTTP requests.
    Raises NotImplementedError if no provider key is available in the environment.
    """
    import httpx

    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")

    # 1. Anthropic API
    if anthropic_key and ("claude" in model.lower() or not (openai_key or gemini_key or groq_key)):
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        # Format messages for Anthropic
        anthropic_msgs: list[dict[str, Any]] = []
        system_prompt: Optional[str] = None
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                system_prompt = str(content)
            elif role in ("user", "assistant"):
                anthropic_msgs.append({"role": role, "content": content})

        payload: dict[str, Any] = {
            "model": model,
            "messages": anthropic_msgs or [{"role": "user", "content": "Hello"}],
            "max_tokens": opts.get("max_tokens", 4096),
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = httpx.post(url, headers=headers, json=payload, timeout=float(timeout))
        response.raise_for_status()
        data = response.json()
        content_blocks = data.get("content", [])
        if content_blocks and "text" in content_blocks[0]:
            return str(content_blocks[0]["text"])
        return str(data)

    # 2. Groq API
    if groq_key and (
        "groq" in model.lower()
        or "qwen" in model.lower()
        or "llama" in model.lower()
        or "gpt-oss" in model.lower()
        or not (anthropic_key or openai_key or gemini_key)
    ):
        return _call_groq(model, messages, groq_key, timeout)

    # 3. OpenAI API
    if openai_key and ("gpt" in model.lower() or "o1" in model.lower() or not (gemini_key or groq_key)):
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model if "gpt" in model.lower() else "gpt-4o",
            "messages": messages,
        }
        response = httpx.post(url, headers=headers, json=payload, timeout=float(timeout))
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])

    # 4. Gemini API
    if gemini_key:
        return _call_gemini(model, messages, gemini_key, timeout)

    raise NotImplementedError(
        f"No LLM provider configured for model '{model}'. "
        "Set ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, or GROQ_API_KEY in .env, "
        "or set a fake handler for testing."
    )


def _call_groq(
    model: str,
    messages: list[dict[str, Any]],
    groq_key: str,
    timeout: int,
) -> str:
    """Helper to execute calls against Groq API."""
    import httpx

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {groq_key}",
        "Content-Type": "application/json",
    }
    clean_model = model.removeprefix("groq/") if model.startswith("groq/") else model
    if not clean_model or clean_model == "default" or "claude" in clean_model:
        clean_model = "qwen/qwen3-8b"
    payload = {
        "model": clean_model,
        "messages": messages,
    }
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=float(timeout))
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])
    except httpx.HTTPStatusError as err:
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if err.response.status_code == 429 and gemini_key:
            return _call_gemini("gemini-flash-lite-latest", messages, gemini_key, timeout)
        raise


def _call_gemini(
    model: str,
    messages: list[dict[str, Any]],
    gemini_key: str,
    timeout: int,
) -> str:
    """Helper to execute calls against Google Gemini API."""
    import httpx

    clean_model = model if "gemini" in model.lower() else "gemini-flash-lite-latest"
    if clean_model in ("gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"):
        clean_model = "gemini-flash-lite-latest"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={gemini_key}"
    headers = {"Content-Type": "application/json"}
    contents = []
    for m in messages:
        role = "user" if m.get("role") in ("user", "system") else "model"
        content = m.get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append({"text": part.get("text", "")})
                elif isinstance(part, dict) and part.get("type") == "image":
                    src = part.get("source", {})
                    if src.get("type") == "base64":
                        parts.append({
                            "inline_data": {
                                "mime_type": src.get("media_type", "image/png"),
                                "data": src.get("data", ""),
                            }
                        })
            contents.append({"role": role, "parts": parts})
        else:
            contents.append({"role": role, "parts": [{"text": str(content)}]})

    payload = {"contents": contents}
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=float(timeout))
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts and "text" in parts[0]:
                return str(parts[0]["text"])
        return str(data)
    except httpx.HTTPStatusError as err:
        groq_key = os.getenv("GROQ_API_KEY")
        if err.response.status_code == 429 and groq_key:
            return _call_groq("qwen/qwen3-8b", messages, groq_key, timeout)
        raise

