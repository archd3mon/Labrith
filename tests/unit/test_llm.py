"""
Tests for lib/llm.py — the thin LLM wrapper.

Covers:
- Fake provider dispatch works.
- Per-agent model resolution from env/config.
- Unknown agent raises ValueError.
- Retry and timeout mechanics (with a fake that fails then succeeds).
- Real provider raises NotImplementedError when no fake is set.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from lib.llm import (
    LLMError,
    complete,
    get_model_for_agent,
    set_fake_llm_handler,
    get_fake_llm_handler,
)


# ---- Fixtures --------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clear_fake():
    """Ensure the fake handler is cleared before and after every test."""
    set_fake_llm_handler(None)
    yield
    set_fake_llm_handler(None)


# ===========================================================================
# Fake provider
# ===========================================================================
class TestFakeProvider:
    def test_fake_handler_dispatched(self):
        def fake(agent_name, messages, **kwargs):
            return f"fake response for {agent_name}"

        set_fake_llm_handler(fake)
        result = complete("planner", [{"role": "user", "content": "hi"}])
        assert result == "fake response for planner"

    def test_fake_receives_model(self):
        captured = {}

        def fake(agent_name, messages, **kwargs):
            captured.update(kwargs)
            return "ok"

        set_fake_llm_handler(fake)
        complete("engineer", [{"role": "user", "content": "build"}])
        assert "model" in captured

    def test_get_fake_returns_none_by_default(self):
        assert get_fake_llm_handler() is None

    def test_get_fake_returns_handler(self):
        handler = lambda *a, **k: "x"
        set_fake_llm_handler(handler)
        assert get_fake_llm_handler() is handler


# ===========================================================================
# Model resolution
# ===========================================================================
class TestModelResolution:
    def test_default_model(self):
        model = get_model_for_agent("planner")
        # Should fall back to default when env var is not set
        assert isinstance(model, str)
        assert len(model) > 0

    def test_env_override(self):
        with mock.patch.dict(os.environ, {"PLANNER_MODEL": "gpt-4o-test"}):
            model = get_model_for_agent("planner")
            assert model == "gpt-4o-test"

    def test_all_agents_have_mapping(self):
        for agent in ("planner", "designer", "engineer", "integration", "qa", "critic"):
            model = get_model_for_agent(agent)
            assert isinstance(model, str)

    def test_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="Unknown agent"):
            get_model_for_agent("hacker")


# ===========================================================================
# complete() — error handling
# ===========================================================================
class TestCompleteErrors:
    def test_unknown_agent_raises(self):
        with pytest.raises(ValueError, match="Unknown agent"):
            complete("hacker", [{"role": "user", "content": "hi"}])

    def test_no_provider_raises_not_implemented(self):
        """Without a fake handler, the real provider raises NotImplementedError,
        which after retries becomes LLMError."""
        with pytest.raises(LLMError, match="failed after"):
            complete(
                "planner",
                [{"role": "user", "content": "hi"}],
                max_retries=1,
            )


# ===========================================================================
# Retry mechanics
# ===========================================================================
class TestRetry:
    def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        def flaky(agent_name, messages, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("transient error")
            return "success after retries"

        set_fake_llm_handler(flaky)
        # The fake handler is called directly, so retries don't apply
        # to the fake path. Test the real-provider retry by using
        # a mock of _call_provider instead.
        set_fake_llm_handler(None)

        with mock.patch("lib.llm._call_provider") as mock_provider:
            call_seq = iter([RuntimeError("fail"), RuntimeError("fail"), "done"])

            def side_effect(*a, **k):
                val = next(call_seq)
                if isinstance(val, Exception):
                    raise val
                return val

            mock_provider.side_effect = side_effect
            result = complete("planner", [{"role": "user", "content": "hi"}], max_retries=3)
            assert result == "done"
            assert mock_provider.call_count == 3

    def test_exhausted_retries_raise_llm_error(self):
        set_fake_llm_handler(None)
        with mock.patch("lib.llm._call_provider", side_effect=RuntimeError("boom")):
            with pytest.raises(LLMError, match="failed after 2 retries"):
                complete(
                    "engineer",
                    [{"role": "user", "content": "x"}],
                    max_retries=2,
                )
