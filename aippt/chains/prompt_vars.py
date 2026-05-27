# -*- coding: utf-8 -*-
"""各 HTML / 模板链路的 invoke 变量组装。"""
from aippt.domain.models import DeckOutline, SlideOutline
from aippt.prompts import PAGE_SUMMARY_EMPTY_FALLBACK, escape_lc_prompt_braces

from .constants import DECK_TEMPLATE_DOC_EXCERPT_CHARS


def deck_outline_compact_lines(deck: DeckOutline) -> str:
    """
    将大纲压缩为有序标题列表。

    @param deck - 已定稿大纲
    @returns 多行字符串
    """
    return "\n".join(f"{i + 1}. {s.title.strip()}" for i, s in enumerate(deck.slides))


def deck_template_prompt_vars(
    deck: DeckOutline,
    document_text: str,
    style_hints_section: str,
    *,
    excerpt_chars: int | None = None,
) -> dict[str, str]:
    """
    组装 deck 模板链路的 invoke 变量。

    @param deck - 大纲对象
    @param document_text - 文档全文
    @param style_hints_section - 风格段或空串
    @param excerpt_chars - 摘录上限；None 用默认
    @returns 模板 human 所需键
    """
    limit = excerpt_chars if excerpt_chars is not None else DECK_TEMPLATE_DOC_EXCERPT_CHARS
    raw = document_text or ""
    excerpt = raw[:limit]
    if len(raw) > limit:
        excerpt += "\n…（摘录结束，后文省略）"
    return {
        "deck_outline_compact": deck_outline_compact_lines(deck),
        "document_excerpt": excerpt,
        "style_hints_section": style_hints_section or "",
    }


def bullets_to_lines(slide: SlideOutline) -> str:
    """
    @param slide - 单页大纲
    @returns 要点多行文本
    """
    return "\n".join(f"- {b}" for b in slide.bullets)


def slide_to_html_prompt_vars(
    slide: SlideOutline,
    *,
    style_hints_section: str = "",
) -> dict[str, str]:
    """
    @param slide - 单页大纲
    @param style_hints_section - 风格段或空串
    @returns HTML 链路输入映射
    """
    summary = (slide.summary or "").strip()
    if not summary:
        summary = PAGE_SUMMARY_EMPTY_FALLBACK
    return {
        "title": slide.title,
        "page_summary": summary,
        "bullets_lines": bullets_to_lines(slide),
        "style_hints_section": style_hints_section or "",
    }


def title_slide_prompt_vars(
    slide: SlideOutline,
    deck_template_html: str,
    style_hints_section: str,
) -> dict[str, str]:
    """组装封面页 invoke 变量。"""
    subtitle = (slide.summary or "").strip()
    if not subtitle:
        subtitle = "（请根据主标题自拟一行副标题，简短有力。）"
    taglines = bullets_to_lines(slide) if slide.bullets else "（无：可不展示列表区块）"
    return {
        "deck_template_html": escape_lc_prompt_braces(deck_template_html),
        "main_title": slide.title,
        "subtitle": subtitle,
        "taglines_block": taglines,
        "style_hints_section": style_hints_section or "",
    }


def toc_slide_prompt_vars(
    slide: SlideOutline,
    deck: DeckOutline,
    deck_template_html: str,
    style_hints_section: str,
) -> dict[str, str]:
    """组装目录页 invoke 变量。"""
    intro = (slide.summary or "").strip()
    if not intro:
        intro = "（请自拟一句简短的目录引导语。）"
    entries = (
        bullets_to_lines(slide)
        if slide.bullets
        else "（要点为空：请根据下列正文标题自拟目录条目，一条一行。）"
    )
    ref_lines = "\n".join(f"{i + 1}. {s.title.strip()}" for i, s in enumerate(deck.slides[2:]))
    if not ref_lines.strip():
        ref_lines = "（暂无正文页标题）"
    return {
        "deck_template_html": escape_lc_prompt_braces(deck_template_html),
        "toc_page_title": slide.title.strip(),
        "toc_intro": intro,
        "toc_entries_lines": entries,
        "content_headings_reference": ref_lines,
        "style_hints_section": style_hints_section or "",
    }


def content_slide_prompt_vars(
    slide: SlideOutline,
    deck_template_html: str,
    style_hints_section: str,
) -> dict[str, str]:
    """组装正文页 invoke 变量。"""
    base = slide_to_html_prompt_vars(slide, style_hints_section=style_hints_section)
    base["deck_template_html"] = escape_lc_prompt_braces(deck_template_html)
    return base
