# -*- coding: utf-8 -*-
"""构造 LangChain 对话模型：Ollama 或 DeepSeek（显式 provider，避免环境变量竞态）。"""
from typing import Any

from langchain_ollama import ChatOllama

from aippt.config import (
    DEEPSEEK_API_BASE,
    DEEPSEEK_API_KEY,
    DEEPSEEK_MODEL,
    LLM_TEMPERATURE,
    OLLAMA_API_KEY,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    get_llm_provider,
    resolve_llm_provider,
)


def build_chat_ollama(*, json_mode: bool = False, extra_kwargs: dict[str, Any] | None = None) -> ChatOllama:
    """
    创建 ChatOllama 实例。

    @param json_mode - True 时请求模型尽量输出合法 JSON
    @param extra_kwargs - 传入 ChatOllama 的额外字段
    @returns 配置好的聊天模型实例
    """
    extra_kwargs = extra_kwargs or {}
    client_headers: dict[str, str] = {}
    if OLLAMA_API_KEY:
        client_headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    kwargs: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "base_url": OLLAMA_BASE_URL,
        "temperature": LLM_TEMPERATURE,
        "validate_model_on_init": False,
    }
    if client_headers:
        kwargs["client_kwargs"] = {"headers": client_headers}
    if json_mode:
        kwargs["format"] = "json"
    kwargs.update(extra_kwargs)
    return ChatOllama(**kwargs)  # type: ignore[arg-type]


def build_chat_deepseek(*, json_mode: bool = False, extra_kwargs: dict[str, Any] | None = None) -> Any:
    """
    创建 DeepSeek OpenAPI 客户端（``langchain_deepseek.ChatDeepSeek``）。

    @param json_mode - True 时启用 JSON Object 输出
    @param extra_kwargs - 构造函数额外字段
    @returns ChatDeepSeek 实例
    @raises ImportError - 未安装 langchain-deepseek
    """
    try:
        from langchain_deepseek import ChatDeepSeek  # noqa: WPS433
    except ImportError as err:
        msg = "使用 DeepSeek 请先安装：pip install langchain-deepseek"
        raise ImportError(msg) from err

    extra_kwargs = extra_kwargs or {}
    merged_model_kw: dict[str, Any] = dict(extra_kwargs.pop("model_kwargs", {}))
    if json_mode:
        merged_model_kw["response_format"] = {"type": "json_object"}

    kwargs: dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "temperature": LLM_TEMPERATURE,
        "api_base": DEEPSEEK_API_BASE,
        "api_key": DEEPSEEK_API_KEY,
    }
    if merged_model_kw:
        kwargs["model_kwargs"] = merged_model_kw
    kwargs.update(extra_kwargs)
    return ChatDeepSeek(**kwargs)


def build_chat_llm(
    *,
    provider: str | None = None,
    json_mode: bool = False,
    extra_kwargs: dict[str, Any] | None = None,
) -> Any:
    """
    按显式 provider 或环境变量 ``LLM_PROVIDER`` 选择后端。

    @param provider - ``ollama`` / ``deepseek``；None 时读环境
    @param json_mode - 是否偏好结构化 JSON
    @param extra_kwargs - 透传构造函数
    @returns LangChain BaseChatModel 兼容实例
    @raises ValueError - provider 非法
    """
    prov = resolve_llm_provider(provider)
    if prov == "ollama":
        return build_chat_ollama(json_mode=json_mode, extra_kwargs=extra_kwargs)
    if prov == "deepseek":
        return build_chat_deepseek(json_mode=json_mode, extra_kwargs=extra_kwargs)
    msg = f"不支持的 LLM_PROVIDER={prov!r}"
    raise ValueError(msg)


def current_provider() -> str:
    """
    @returns 当前生效的 provider 标识（无显式参数时等同环境变量）
    """
    return get_llm_provider()
