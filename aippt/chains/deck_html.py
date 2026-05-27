# -*- coding: utf-8 -*-
"""单页 / deck 模板 HTML 生成 LCEL 链路（raster_screen）。"""
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from aippt.parsers import strip_fence
from aippt.prompts import (
    HTML_SLIDE_HUMAN_PROMPT,
    RASTER_CONTENT_SLIDE_HUMAN_PROMPT,
    RASTER_DECK_TEMPLATE_HUMAN_PROMPT,
    RASTER_TITLE_SLIDE_HUMAN_PROMPT,
    RASTER_TOC_SLIDE_HUMAN_PROMPT,
    build_raster_content_slide_system_prompt,
    build_raster_deck_template_system_prompt,
    build_raster_screen_html_system_prompt,
    build_raster_title_slide_system_prompt,
    build_raster_toc_slide_system_prompt,
    escape_lc_prompt_braces,
)
from aippt.prompts import RASTER_SCREEN_LAYOUT_CSS

from .constants import HtmlSlideChainKind, RASTER_EXPORT_VIEWPORT_H, RASTER_EXPORT_VIEWPORT_W


def build_html_slide_chat_template() -> ChatPromptTemplate:
    """构建独立单页 HTML 的 ChatPromptTemplate。"""
    layout_block = escape_lc_prompt_braces(RASTER_SCREEN_LAYOUT_CSS)
    system_prompt = build_raster_screen_html_system_prompt(
        layout_block,
        RASTER_EXPORT_VIEWPORT_W,
        RASTER_EXPORT_VIEWPORT_H,
    )
    return ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", HTML_SLIDE_HUMAN_PROMPT)]
    )


def build_raster_deck_template_chat_template() -> ChatPromptTemplate:
    """raster_screen：deck_template.html 模板。"""
    layout_block = escape_lc_prompt_braces(RASTER_SCREEN_LAYOUT_CSS)
    system_prompt = build_raster_deck_template_system_prompt(
        layout_block,
        RASTER_EXPORT_VIEWPORT_W,
        RASTER_EXPORT_VIEWPORT_H,
    )
    return ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", RASTER_DECK_TEMPLATE_HUMAN_PROMPT)]
    )


def build_raster_title_slide_chat_template() -> ChatPromptTemplate:
    """raster_screen：封面单页模板。"""
    layout_block = escape_lc_prompt_braces(RASTER_SCREEN_LAYOUT_CSS)
    system_prompt = build_raster_title_slide_system_prompt(
        layout_block,
        RASTER_EXPORT_VIEWPORT_W,
        RASTER_EXPORT_VIEWPORT_H,
    )
    return ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", RASTER_TITLE_SLIDE_HUMAN_PROMPT)]
    )


def build_raster_content_slide_chat_template() -> ChatPromptTemplate:
    """raster_screen：正文单页模板。"""
    layout_block = escape_lc_prompt_braces(RASTER_SCREEN_LAYOUT_CSS)
    system_prompt = build_raster_content_slide_system_prompt(
        layout_block,
        RASTER_EXPORT_VIEWPORT_W,
        RASTER_EXPORT_VIEWPORT_H,
    )
    return ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", RASTER_CONTENT_SLIDE_HUMAN_PROMPT)]
    )


def build_raster_toc_slide_chat_template() -> ChatPromptTemplate:
    """raster_screen：目录单页模板。"""
    layout_block = escape_lc_prompt_braces(RASTER_SCREEN_LAYOUT_CSS)
    system_prompt = build_raster_toc_slide_system_prompt(
        layout_block,
        RASTER_EXPORT_VIEWPORT_W,
        RASTER_EXPORT_VIEWPORT_H,
    )
    return ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("human", RASTER_TOC_SLIDE_HUMAN_PROMPT)]
    )


def format_html_slide_prompt_dump(
    *,
    variables: dict[str, str],
    chain_kind: HtmlSlideChainKind = "slide",
) -> str:
    """
    将单页 HTML 提示渲染为可读文本（便于落盘核对）。

    @param variables - invoke 变量表
    @param chain_kind - 链路类型
    @returns UTF-8 文本
    """
    if chain_kind == "deck_template":
        tpl = build_raster_deck_template_chat_template()
    elif chain_kind == "title":
        tpl = build_raster_title_slide_chat_template()
    elif chain_kind == "toc":
        tpl = build_raster_toc_slide_chat_template()
    elif chain_kind == "content":
        tpl = build_raster_content_slide_chat_template()
    else:
        tpl = build_html_slide_chat_template()

    msgs = tpl.format_messages(**variables)
    blocks: list[str] = []
    for m in msgs:
        role = getattr(m, "type", None) or type(m).__name__
        blocks.append(f"========== {role} ==========\n{m.content}")
    return "\n\n".join(blocks).strip() + "\n"


def _html_chain_clean(llm: Any, tpl: ChatPromptTemplate):
    """ChatPromptTemplate → LLM → 去 html 围栏。"""

    def _clean_html(msg: Any) -> str:
        body = str(msg.content).strip()
        return strip_fence(body, "html")

    return tpl | llm | RunnableLambda(_clean_html)


def build_html_slide_chain(llm: Any):
    """独立单页 HTML 链路（无 deck 模板嵌入）。"""
    return _html_chain_clean(llm, build_html_slide_chat_template())


def build_deck_html_template_chain(llm: Any):
    """deck_template.html 全文链路。"""
    return _html_chain_clean(llm, build_raster_deck_template_chat_template())


def build_raster_title_slide_chain(llm: Any):
    """封面单页 HTML 链路。"""
    return _html_chain_clean(llm, build_raster_title_slide_chat_template())


def build_raster_toc_slide_chain(llm: Any):
    """目录单页 HTML 链路。"""
    return _html_chain_clean(llm, build_raster_toc_slide_chat_template())


def build_raster_content_slide_chain(llm: Any):
    """正文单页 HTML 链路。"""
    return _html_chain_clean(llm, build_raster_content_slide_chat_template())
