# -*- coding: utf-8 -*-
"""链路与导出相关的常量。"""
from typing import Literal

from aippt.export.html_to_ppt import (
    DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX,
    default_playwright_viewport_height_px,
)

RASTER_EXPORT_VIEWPORT_W = DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX
RASTER_EXPORT_VIEWPORT_H = default_playwright_viewport_height_px(width_px=RASTER_EXPORT_VIEWPORT_W)

DECK_TEMPLATE_HTML_FILENAME = "deck_template.html"
DECK_TEMPLATE_DOC_EXCERPT_CHARS = 6000

HtmlSlideChainKind = Literal["slide", "deck_template", "title", "toc", "content"]
