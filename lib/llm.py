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
_DEFAULT_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
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
    model = get_model_for_agent(agent_name)
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

    This function isolates all provider-specific logic.  In v1 it raises
    NotImplementedError until a real provider SDK is wired in.
    """
    raise NotImplementedError(
        f"No LLM provider configured for model '{model}'. "
        "Set a fake handler for testing or implement _call_provider()."
    )
