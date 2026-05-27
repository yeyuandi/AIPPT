# -*- coding: utf-8 -*-
"""大纲生成编排（CLI / Web 共用，无 HTTP 依赖）。"""
from __future__ import annotations

from aippt.chains import (
    build_outline_chain,
    format_outline_max_slides_instruction,
    format_outline_target_slides_instruction,
    validate_outline_slides_cli,
)
from aippt.config import OUTLINE_AUTO_PAGES_HARD_CAP, provider_auth_error_message
from aippt.domain.models import DeckOutline
from aippt.llm import build_chat_llm


def meta_llm_provider(meta: dict | None) -> str | None:
    """
    从任务 meta 读取 provider。

    @param meta - meta.json 内容或 None
    @returns ollama/deepseek 或 None（沿用环境）
    """
    if not meta:
        return None
    p = (meta.get("llm_provider") or "").strip().lower()
    return p if p in ("ollama", "deepseek") else None


def cap_outline_pages(outline: DeckOutline, max_slides: int | None) -> None:
    """
    按 CLI / Web 相同规则裁剪大纲页数（就地修改）。

    @param outline - 大纲对象
    @param max_slides - 用户硬上限；None 时仅用脚本硬上限
    @returns None
    """
    raw = len(outline.slides)
    if max_slides is not None and raw > max_slides:
        outline.slides = outline.slides[:max_slides]
    elif max_slides is None and raw > OUTLINE_AUTO_PAGES_HARD_CAP:
        outline.slides = outline.slides[:OUTLINE_AUTO_PAGES_HARD_CAP]


def invoke_outline_chain(
    document: str,
    *,
    max_slides: int | None,
    target_slides: int | None,
    provider: str | None = None,
) -> DeckOutline:
    """
    调用 LLM 生成大纲（含鉴权与页数参数校验）。

    @param document - 正文全文
    @param max_slides - 页数硬上限
    @param target_slides - 页数软目标
    @param provider - 任务级 provider，None 读环境
    @returns DeckOutline
    @raises RuntimeError - 密钥或配置缺失
    @raises ValueError - 页数参数非法
    """
    auth = provider_auth_error_message(provider)
    if auth is not None:
        raise RuntimeError(auth.strip())

    slides_err = validate_outline_slides_cli(max_slides, target_slides)
    if slides_err is not None:
        raise ValueError(slides_err.strip())

    outline_llm = build_chat_llm(provider=provider, json_mode=True)
    outline_chain = build_outline_chain(outline_llm)
    return outline_chain.invoke(
        {
            "document": document,
            "max_slides_instruction": format_outline_max_slides_instruction(max_slides),
            "target_slides_instruction": format_outline_target_slides_instruction(
                target_slides,
                max_slides=max_slides,
            ),
        }
    )
