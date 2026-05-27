# -*- coding: utf-8 -*-
"""领域模型（无 LangChain / Flask 依赖）。"""
from .models import (
    DeckOutline,
    SlideOutline,
    assign_slide_output_filenames,
    deck_outline_to_json,
    format_deck_outline_plain,
)

__all__ = [
    "DeckOutline",
    "SlideOutline",
    "assign_slide_output_filenames",
    "deck_outline_to_json",
    "format_deck_outline_plain",
]
