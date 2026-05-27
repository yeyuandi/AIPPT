# -*- coding: utf-8 -*-
"""媒体处理子包（FFmpeg 图片 + 音频 + 字幕 → 视频等）。"""

__all__ = [
    "DEFAULT_SUBTITLE_FORCE_STYLE",
    "FfmpegComposeOptions",
    "FfmpegVideoComposer",
    "compose_image_audio_subtitles",
    "find_ffmpeg_executable",
    "build_subtitles_vf",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import ffmpeg_tools

    return getattr(ffmpeg_tools, name)
