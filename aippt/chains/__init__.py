# -*- coding: utf-8 -*-
"""LangChain LCEL 链路（提示词见 ``aippt.prompts``）。"""
from aippt.prompts import (
    format_html_style_hints_section,
    format_outline_max_slides_instruction,
    format_outline_target_slides_instruction,
    validate_outline_slides_cli,
)

from .constants import DECK_TEMPLATE_HTML_FILENAME, HtmlSlideChainKind
from .deck_html import (
    build_deck_html_template_chain,
    build_html_slide_chain,
    build_html_slide_chat_template,
    build_raster_content_slide_chain,
    build_raster_title_slide_chain,
    build_raster_toc_slide_chain,
    format_html_slide_prompt_dump,
)
from .outline import build_outline_chain
from .prompt_vars import (
    bullets_to_lines,
    content_slide_prompt_vars,
    deck_outline_compact_lines,
    deck_template_prompt_vars,
    slide_to_html_prompt_vars,
    title_slide_prompt_vars,
    toc_slide_prompt_vars,
)
from aippt.parsers import parse_outline_json

__all__ = [
    "DECK_TEMPLATE_HTML_FILENAME",
    "HtmlSlideChainKind",
    "build_deck_html_template_chain",
    "build_html_slide_chain",
    "build_html_slide_chat_template",
    "build_outline_chain",
    "build_raster_content_slide_chain",
    "build_raster_title_slide_chain",
    "build_raster_toc_slide_chain",
    "bullets_to_lines",
    "content_slide_prompt_vars",
    "deck_outline_compact_lines",
    "deck_template_prompt_vars",
    "format_html_slide_prompt_dump",
    "format_html_style_hints_section",
    "format_outline_max_slides_instruction",
    "format_outline_target_slides_instruction",
    "parse_outline_json",
    "slide_to_html_prompt_vars",
    "title_slide_prompt_vars",
    "toc_slide_prompt_vars",
    "validate_outline_slides_cli",
]
