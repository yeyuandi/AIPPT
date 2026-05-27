# -*- coding: utf-8 -*-
"""LLM 工厂（langchain-* partner 包）。"""
from .factory import (
    build_chat_deepseek,
    build_chat_llm,
    build_chat_ollama,
    current_provider,
)

__all__ = [
    "build_chat_deepseek",
    "build_chat_llm",
    "build_chat_ollama",
    "current_provider",
]
