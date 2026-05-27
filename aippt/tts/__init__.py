# -*- coding: utf-8 -*-
"""语音合成子包（Microsoft Edge 在线 TTS / edge-tts）。"""

__all__ = [
    "EDGE_TTS_PARAMETER_CATALOG",
    "EdgeTtsSynthesizeOptions",
    "format_parameter_catalog_text",
    "list_edge_voices",
    "synthesize_to_file",
]


def __getattr__(name: str):
    """延迟导入，避免 ``python -m aippt.tts.edge_tts_tools`` 时重复加载子模块。"""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import edge_tts_tools

    return getattr(edge_tts_tools, name)
