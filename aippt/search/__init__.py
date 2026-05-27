# -*- coding: utf-8 -*-
"""联网检索子包（DuckDuckGo / duckduckgo-search）。"""

__all__ = [
    "DDGS_PARAMETER_CATALOG",
    "DuckDuckGoClientOptions",
    "DuckDuckGoSearchTool",
    "format_parameter_catalog_text",
    "search_images",
    "search_news",
    "search_text",
    "search_videos",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import duckduckgo_tools

    return getattr(duckduckgo_tools, name)
