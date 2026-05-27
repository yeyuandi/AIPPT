# -*- coding: utf-8 -*-
"""
edge-tts 工具封装：合成语音、列出音色，并集中说明 ``Communicate`` / CLI 全部参数。

依赖：``pip install edge-tts``（见仓库根 ``requirements.txt``）。

本地测试::

    python -m aippt.tts.edge_tts_tools --list-params
    python -m aippt.tts.edge_tts_tools --list-voices
    python -m aippt.tts.edge_tts_tools -t "你好，这是测试。" -o out/test.mp3
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional, TypedDict

# ---------------------------------------------------------------------------
# edge-tts 参数目录（与 rany2/edge-tts Communicate、CLI util 对齐）
# ---------------------------------------------------------------------------

class EdgeTtsParamSpec(TypedDict):
    """单条参数说明（供文档与 ``--list-params`` 打印）。"""

    group: str
    name: str
    type_hint: str
    default: str
    description: str


EDGE_TTS_PARAMETER_CATALOG: list[EdgeTtsParamSpec] = [
    # Communicate 构造参数
    {
        "group": "Communicate.__init__",
        "name": "text",
        "type_hint": "str",
        "default": "（必填）",
        "description": "待朗读正文；内部会去除不兼容控制字符并按约 4096 字节分块请求。",
    },
    {
        "group": "Communicate.__init__",
        "name": "voice",
        "type_hint": "str",
        "default": "zh-CN-XiaoxiaoNeural（库内 DEFAULT_VOICE，以 edge_tts.constants 为准）",
        "description": "音色 ShortName，可用 list_voices() / --list-voices 查看。",
    },
    {
        "group": "Communicate.__init__",
        "name": "rate",
        "type_hint": "str",
        "default": "+0%",
        "description": "语速，百分比字符串，如 +20%、-30%。",
    },
    {
        "group": "Communicate.__init__",
        "name": "volume",
        "type_hint": "str",
        "default": "+0%",
        "description": "音量，百分比字符串，如 +10%、-50%。",
    },
    {
        "group": "Communicate.__init__",
        "name": "pitch",
        "type_hint": "str",
        "default": "+0Hz",
        "description": "音调，赫兹偏移字符串，如 +5Hz、-10Hz。",
    },
    {
        "group": "Communicate.__init__",
        "name": "boundary",
        "type_hint": "Literal['WordBoundary', 'SentenceBoundary']",
        "default": "SentenceBoundary",
        "description": "字幕/元数据边界粒度；影响 stream() 返回的边界事件类型。",
    },
    {
        "group": "Communicate.__init__",
        "name": "connector",
        "type_hint": "Optional[aiohttp.BaseConnector]",
        "default": "None",
        "description": "自定义 aiohttp 连接器（高级用法）。",
    },
    {
        "group": "Communicate.__init__",
        "name": "proxy",
        "type_hint": "Optional[str]",
        "default": "None",
        "description": "HTTP/HTTPS 代理 URL，用于访问 Edge TTS 服务与 list_voices。",
    },
    {
        "group": "Communicate.__init__",
        "name": "connect_timeout",
        "type_hint": "int",
        "default": "10",
        "description": "套接字连接超时（秒）。",
    },
    {
        "group": "Communicate.__init__",
        "name": "receive_timeout",
        "type_hint": "int",
        "default": "60",
        "description": "套接字读取超时（秒）。",
    },
    # Communicate 实例方法
    {
        "group": "Communicate.save",
        "name": "audio_fname",
        "type_hint": "str | bytes",
        "default": "（必填）",
        "description": "输出音频文件路径（通常为 .mp3）。",
    },
    {
        "group": "Communicate.save",
        "name": "metadata_fname",
        "type_hint": "Optional[str | bytes]",
        "default": "None",
        "description": "官方 save 写入的是 JSON 行元数据，非 SRT。本包 synthesize_to_file(metadata_path=...) 改用 SubMaker 写标准 SRT。",
    },
    {
        "group": "Communicate.stream",
        "name": "（无参）",
        "type_hint": "AsyncGenerator",
        "default": "—",
        "description": "异步流式返回 audio / WordBoundary / SentenceBoundary 块；每实例仅能调用一次。",
    },
    # 模块级 API
    {
        "group": "edge_tts.list_voices",
        "name": "proxy",
        "type_hint": "Optional[str]",
        "default": "None",
        "description": "列出全部可用音色时的代理，与 Communicate.proxy 相同。",
    },
    # 官方 CLI（edge-tts 命令）额外参数
    {
        "group": "CLI（edge-tts 可执行文件）",
        "name": "--text / -t",
        "type_hint": "str",
        "default": "—",
        "description": "命令行直接传入朗读文本（与 --file 二选一）。",
    },
    {
        "group": "CLI（edge-tts 可执行文件）",
        "name": "--file / -f",
        "type_hint": "path",
        "default": "—",
        "description": "从文件读取文本（与 --text 二选一）。",
    },
    {
        "group": "CLI（edge-tts 可执行文件）",
        "name": "--list-voices / -l",
        "type_hint": "flag",
        "default": "false",
        "description": "打印音色表后退出。",
    },
    {
        "group": "CLI（edge-tts 可执行文件）",
        "name": "--write-media",
        "type_hint": "path",
        "default": "stdout",
        "description": "音频写入文件；未指定时可能写入终端。",
    },
    {
        "group": "CLI（edge-tts 可执行文件）",
        "name": "--write-subtitles",
        "type_hint": "path",
        "default": "stderr",
        "description": "字幕写入文件。",
    },
]


def format_parameter_catalog_text() -> str:
    """
    将 ``EDGE_TTS_PARAMETER_CATALOG`` 格式化为可读文本。

    @returns 多行说明字符串
    """
    lines: list[str] = ["edge-tts 参数一览", "=" * 72, ""]
    current_group = ""
    for spec in EDGE_TTS_PARAMETER_CATALOG:
        if spec["group"] != current_group:
            current_group = spec["group"]
            lines.append(f"[{current_group}]")
        lines.append(f"  {spec['name']}")
        lines.append(f"    类型: {spec['type_hint']}")
        lines.append(f"    默认: {spec['default']}")
        lines.append(f"    说明: {spec['description']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@dataclass
class EdgeTtsSynthesizeOptions:
    """
    本包 ``synthesize_to_file`` 使用的合成选项（映射到 ``edge_tts.Communicate``）。

    @ivar voice - 音色 ShortName
    @ivar rate - 语速百分比字符串
    @ivar volume - 音量百分比字符串
    @ivar pitch - 音调 Hz 字符串
    @ivar boundary - 边界事件类型
    @ivar proxy - 代理 URL
    @ivar connect_timeout - 连接超时（秒）
    @ivar receive_timeout - 读取超时（秒）
    @ivar metadata_path - 若设置则同时写入字幕文件
    """

    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    boundary: Literal["WordBoundary", "SentenceBoundary"] = "SentenceBoundary"
    proxy: Optional[str] = None
    connect_timeout: int = 10
    receive_timeout: int = 60
    metadata_path: Optional[Path] = None


async def list_edge_voices(*, proxy: Optional[str] = None) -> list[dict[str, Any]]:
    """
    列出 Edge TTS 可用音色。

    @param proxy - 可选代理
    @returns 音色字典列表（与 edge_tts.list_voices 一致）
    """
    import edge_tts

    return await edge_tts.list_voices(proxy=proxy)


async def synthesize_to_file(
    text: str,
    output_path: Path | str,
    *,
    options: EdgeTtsSynthesizeOptions | None = None,
) -> Path:
    """
    将文本合成为音频；若指定 ``metadata_path`` 则用 ``SubMaker`` 写出标准多行 SRT。

    注意：``Communicate.save(..., metadata_fname)`` 官方实现写的是 JSON 行，不是 SRT；
    本函数在需要字幕时会自行 ``stream`` + ``SubMaker.get_srt()``。

    @param text - 待朗读正文（多句、多段会对应 SRT 中多条字幕）
    @param output_path - 输出 .mp3（或库支持的格式）路径
    @param options - 合成参数；None 时使用默认
    @returns 写入后的音频绝对路径
    """
    import edge_tts
    from edge_tts import SubMaker

    opts = options or EdgeTtsSynthesizeOptions()
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    communicate = edge_tts.Communicate(
        text,
        opts.voice,
        rate=opts.rate,
        volume=opts.volume,
        pitch=opts.pitch,
        boundary=opts.boundary,
        proxy=opts.proxy,
        connect_timeout=opts.connect_timeout,
        receive_timeout=opts.receive_timeout,
    )

    if opts.metadata_path is None:
        await communicate.save(str(out))
        return out

    sub_path = Path(opts.metadata_path).resolve()
    sub_path.parent.mkdir(parents=True, exist_ok=True)
    submaker = SubMaker()
    with open(out, "wb") as audio_f:
        async for message in communicate.stream():
            if message["type"] == "audio":
                audio_f.write(message["data"])
            elif message["type"] in ("WordBoundary", "SentenceBoundary"):
                submaker.feed(message)
    sub_path.write_text(submaker.get_srt(), encoding="utf-8")
    return out


def _print_voices_table(voices: list[dict[str, Any]]) -> None:
    """在终端打印音色简表。"""
    voices = sorted(voices, key=lambda v: str(v.get("ShortName", "")))
    print(f"{'ShortName':<42} {'Gender':<8} ContentCategories")
    print("-" * 90)
    for v in voices:
        short = str(v.get("ShortName", ""))
        gender = str(v.get("Gender", ""))
        tag = v.get("VoiceTag") or {}
        cats = ", ".join(tag.get("ContentCategories") or []) if isinstance(tag, dict) else ""
        print(f"{short:<42} {gender:<8} {cats}")


def _build_arg_parser() -> argparse.ArgumentParser:
    """构造本模块测试用 CLI。"""
    p = argparse.ArgumentParser(
        description="aippt edge-tts 工具：列出参数/音色，或将文本合成为音频。",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--list-params",
        action="store_true",
        help="打印 edge-tts 全部参数说明后退出",
    )
    g.add_argument(
        "--list-voices",
        action="store_true",
        help="打印可用音色后退出",
    )
    g.add_argument("-t", "--text", help="待合成文本")
    g.add_argument("-f", "--file", type=Path, help="从 UTF-8 文件读取文本")

    p.add_argument("-o", "--output", type=Path, help="输出音频路径（默认 output_run/tts_test.mp3）")
    p.add_argument(
        "-v",
        "--voice",
        default="zh-CN-XiaoxiaoNeural",
        help="音色 ShortName",
    )
    p.add_argument("--rate", default="+0%", help="语速，如 +20%%、-30%%")
    p.add_argument("--volume", default="+0%", help="音量，如 +10%%、-50%%")
    p.add_argument("--pitch", default="+0Hz", help="音调，如 +5Hz、-10Hz")
    p.add_argument(
        "--boundary",
        choices=("WordBoundary", "SentenceBoundary"),
        default="SentenceBoundary",
        help="边界事件类型",
    )
    p.add_argument("--proxy", default=None, help="HTTP(S) 代理")
    p.add_argument("--connect-timeout", type=int, default=10, help="连接超时（秒）")
    p.add_argument("--receive-timeout", type=int, default=60, help="读取超时（秒）")
    p.add_argument("--metadata", type=Path, default=None, help="可选字幕输出路径（.srt）")
    return p


async def _amain(argv: list[str] | None = None) -> int:
    """
    异步入口：解析命令行并执行 list-params / list-voices / 合成。

    @param argv - 命令行参数；None 表示 sys.argv[1:]
    @returns 进程退出码
    """
    args = _build_arg_parser().parse_args(argv)

    if args.list_params:
        print(format_parameter_catalog_text())
        return 0

    if args.list_voices:
        voices = await list_edge_voices(proxy=args.proxy)
        _print_voices_table(voices)
        print(f"\n共 {len(voices)} 个音色。")
        return 0

    text = args.text
    if args.file is not None:
        text = args.file.read_text(encoding="utf-8")
    if not text or not str(text).strip():
        print("请提供 -t/--text 或 -f/--file。", file=sys.stderr)
        return 2

    out = args.output
    if out is None:
        out = Path("output_run") / "tts_test.mp3"

    opts = EdgeTtsSynthesizeOptions(
        voice=args.voice,
        rate=args.rate,
        volume=args.volume,
        pitch=args.pitch,
        boundary=args.boundary,
        proxy=args.proxy,
        connect_timeout=args.connect_timeout,
        receive_timeout=args.receive_timeout,
        metadata_path=args.metadata,
    )
    path = await synthesize_to_file(text, out, options=opts)
    print(f"已写入: {path}")
    if args.metadata:
        print(f"字幕: {args.metadata.resolve()}")
    return 0


def main() -> None:
    """``python -m aippt.tts.edge_tts_tools`` 入口。"""
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
