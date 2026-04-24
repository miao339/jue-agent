"""Tests for the Nous-Jue-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"jue"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``jue-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "jue" tag namespace.

``is_nous_jue_non_agentic`` should only match the actual Nous Research
Jue-3 / Jue-4 chat family.
"""

from __future__ import annotations

import pytest

from hermes_cli.model_switch import (
    _JUE_MODEL_WARNING,
    _check_jue_model_warning,
    is_nous_jue_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "NousResearch/Jue-3-Llama-3.1-70B",
        "NousResearch/Jue-3-Llama-3.1-405B",
        "jue-3",
        "Jue-3",
        "jue-4",
        "jue-4-405b",
        "jue_4_70b",
        "openrouter/jue3:70b",
        "openrouter/nousresearch/jue-4-405b",
        "NousResearch/Hermes3",
        "jue-3.1",
    ],
)
def test_matches_real_nous_jue_chat_models(model_name: str) -> None:
    assert is_nous_jue_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Nous Jue 3/4"
    )
    assert _check_jue_model_warning(model_name) == _JUE_MODEL_WARNING


@pytest.mark.parametrize(
    "model_name",
    [
        # Kyle's local Modelfile — qwen3:14b under a custom tag
        "jue-brain:qwen3-14b-ctx16k",
        "jue-brain:qwen3-14b-ctx32k",
        "jue-honcho:qwen3-8b-ctx8k",
        # Plain unrelated models
        "qwen3:14b",
        "qwen3-coder:30b",
        "qwen2.5:14b",
        "claude-opus-4-6",
        "anthropic/claude-sonnet-4.5",
        "gpt-5",
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "deepseek-chat",
        # Non-chat Jue models we don't warn about
        "jue-llm-2",
        "jue2-pro",
        "nous-jue-2-mistral",
        # Edge cases
        "",
        "jue",  # bare "jue" isn't the 3/4 family
        "jue-brain",
        "brain-jue-3-impostor",  # "3" not preceded by /: boundary
    ],
)
def test_does_not_match_unrelated_models(model_name: str) -> None:
    assert not is_nous_jue_non_agentic(model_name), (
        f"expected {model_name!r} NOT to be flagged as Nous Jue 3/4"
    )
    assert _check_jue_model_warning(model_name) == ""


def test_none_like_inputs_are_safe() -> None:
    assert is_nous_jue_non_agentic("") is False
    # Defensive: the helper shouldn't crash on None-ish falsy input either.
    assert _check_jue_model_warning("") == ""
