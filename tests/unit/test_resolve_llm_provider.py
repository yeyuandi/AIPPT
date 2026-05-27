# -*- coding: utf-8 -*-
"""provider 解析与鉴权辅助测试。"""
import os

from aippt.config import resolve_llm_provider


def test_resolve_llm_provider_explicit():
    """显式 provider 应覆盖环境。"""
    old = os.environ.get("LLM_PROVIDER")
    try:
        os.environ["LLM_PROVIDER"] = "deepseek"
        assert resolve_llm_provider("ollama") == "ollama"
    finally:
        if old is None:
            os.environ.pop("LLM_PROVIDER", None)
        else:
            os.environ["LLM_PROVIDER"] = old
