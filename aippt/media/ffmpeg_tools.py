# -*- coding: utf-8 -*-
"""
FFmpeg 工具：静态图 + 音频 + SRT 字幕 → MP4。

字幕样式（libass ``force_style``）默认：
白色主色、黑色描边、底部居中，参考::

    subtitles=subtitle.srt:force_style='FontName=SimHei,FontSize=30,...'

依赖：系统已安装 ``ffmpeg`` 且可在 PATH 中调用（本包不通过 pip 安装 FFmpeg）。

本地测试::

    python -m aippt.media.ffmpeg_tools -i slide.png -a narration.mp3 -s subtitle.srt -o output_run/demo.mp4
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# ASS：PrimaryColour / OutlineColour 为 &HAABBGGRR&；Alignment=2 为底部居中
DEFAULT_SUBTITLE_FORCE_STYLE = (
    "FontName=SimHei,"
    "FontSize=30,"
    "PrimaryColour=&H00FFFFFF&,"
    "BackColour=&H80000000&,"
    "OutlineColour=&H00000000&,"
    "OutlineWidth=2,"
    "MarginV=45,"
    "Alignment=2"
)


@dataclass
class FfmpegComposeOptions:
    """
    图片 + 音频 + 字幕 合成选项。

    @ivar width - 输出视频宽度（像素）
    @ivar height - 输出视频高度（像素）
    @ivar fps - 静图序列帧率（配合 loop 使用；常用 25/30）
    @ivar video_codec - 视频编码器
    @ivar audio_codec - 音频编码器
    @ivar audio_bitrate - 音频码率（如 192k）
    @ivar pixel_format - 像素格式（播放器兼容常用 yuv420p）
    @ivar subtitle_force_style - libass force_style 字符串
    @ivar extra_vf - 追加到 -vf 链末尾的滤镜（可选，不含 leading 逗号）
    @ivar ffmpeg_loglevel - FFmpeg 日志级别
    """

    width: int = 1920
    height: int = 1080
    fps: int = 25
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    pixel_format: str = "yuv420p"
    subtitle_force_style: str = field(default_factory=lambda: DEFAULT_SUBTITLE_FORCE_STYLE)
    extra_vf: str = ""
    ffmpeg_loglevel: str = "warning"


def find_ffmpeg_executable(explicit: str | None = None) -> str:
    """
    解析 ffmpeg 可执行文件路径。

    @param explicit - 显式路径；为 None 时在 PATH 中查找 ``ffmpeg``
    @returns ffmpeg 可执行文件路径
    @raises FileNotFoundError - 未找到
    """
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return str(p.resolve())
        raise FileNotFoundError(f"指定的 ffmpeg 不存在: {explicit}")
    found = shutil.which("ffmpeg")
    if not found:
        raise FileNotFoundError(
            "未在 PATH 中找到 ffmpeg。请安装 FFmpeg 并加入系统 PATH，"
            "或通过 FfmpegVideoComposer(ffmpeg_bin=...) 指定路径。"
        )
    return found


def escape_subtitle_filter_token(token: str) -> str:
    """
    转义 ``subtitles=`` 滤镜中的路径 token（应为相对文件名，勿含 ``盘符:``）。

    @param token - 相对路径或纯文件名（POSIX 分隔符）
    @returns 转义后的 token
    """
    s = token.replace("\\", "/")
    for ch in ("'", ",", "[", "]", ":", ";"):
        s = s.replace(ch, f"\\{ch}")
    return s


def resolve_subtitle_vf_token(
    subtitles_path: Path,
    work_dir: Path,
) -> tuple[str, Path | None]:
    """
    为 ``subtitles`` 滤镜生成不含 Windows 盘符的路径 token。

    FFmpeg 在 ``-vf`` 里解析 ``E\\:/path`` 会失败；改为在 ``work_dir`` 下使用相对路径，
    调用方须 ``subprocess.run(..., cwd=work_dir)``。若字幕不在该目录则复制到临时文件。

    @param subtitles_path - SRT 绝对路径
    @param work_dir - 工作目录（通常为输出 MP4 所在目录）
    @returns (滤镜用 token, 临时字幕路径或 None)
    """
    work_dir = work_dir.resolve()
    subs = subtitles_path.resolve()
    try:
        rel = subs.relative_to(work_dir)
        return escape_subtitle_filter_token(rel.as_posix()), None
    except ValueError:
        tmp = work_dir / f".ffmpeg_subs_{subs.name}"
        shutil.copy2(subs, tmp)
        return escape_subtitle_filter_token(tmp.name), tmp


def escape_force_style_for_filter(force_style: str) -> str:
    """
    转义 ``force_style`` 供写入 ``-vf``（``&``、``'`` 在 libavfilter 中有特殊含义）。

    @param force_style - libass force_style 原文
    @returns 转义后的字符串（仍由外层单引号包裹）
    """
    s = force_style.replace("\\", "\\\\")
    s = s.replace("'", r"\'")
    s = s.replace("&", r"\&")
    return s


def assert_valid_srt_file(path: Path) -> None:
    """
    粗略校验字幕文件为 SRT/VTT，而非 edge-tts 误存的 JSON 元数据。

    @param path - 字幕路径
    @raises ValueError - 内容明显不是字幕格式
    """
    head = path.read_text(encoding="utf-8-sig").lstrip()[:256]
    if not head:
        return
    if head.startswith("{") or head.startswith("["):
        raise ValueError(
            f"字幕文件不是标准 SRT，似为 JSON 元数据：{path}\n"
            "请用 edge-tts 生成时指定 --metadata xxx.srt（由 SubMaker 写入），"
            "或自行提供符合 SRT 规范的 .srt 文件。"
        )


def build_subtitles_vf(subtitle_token: str, force_style: str) -> str:
    """
    构造烧录字幕的 ``subtitles=...:force_style='...'`` 滤镜片段。

    @param subtitle_token - 经 ``resolve_subtitle_vf_token`` 得到的相对路径 token
    @param force_style - libass force_style 内容（不含外层引号）
    @returns 滤镜字符串，可拼入 ``-vf`` 链
    """
    style_escaped = escape_force_style_for_filter(force_style)
    return f"subtitles={subtitle_token}:force_style='{style_escaped}'"


def build_scale_pad_vf(width: int, height: int) -> str:
    """
    缩放并居中填充到目标分辨率（保持宽高比）。

    @param width - 目标宽
    @param height - 目标高
    @returns scale+pad 滤镜链
    """
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )


class FfmpegVideoComposer:
    """
    使用 FFmpeg 将静态图、音频、SRT 字幕合成为 MP4。

    流程：``loop`` 静图 + 音频 ``-shortest`` 对齐时长，``-vf`` 内 ``scale/pad`` 后烧录字幕。
    """

    def __init__(
        self,
        options: FfmpegComposeOptions | None = None,
        *,
        ffmpeg_bin: str | None = None,
    ) -> None:
        """
        @param options - 合成参数；None 为默认
        @param ffmpeg_bin - ffmpeg 可执行文件路径；None 则从 PATH 查找
        """
        self.options = options or FfmpegComposeOptions()
        self._ffmpeg_bin: str | None = ffmpeg_bin

    @property
    def ffmpeg_bin(self) -> str:
        """已解析的 ffmpeg 路径（惰性查找）。"""
        if self._ffmpeg_bin is None:
            self._ffmpeg_bin = find_ffmpeg_executable()
        return self._ffmpeg_bin

    def build_vf_chain(self, subtitle_token: str) -> str:
        """
        组装完整 ``-vf`` 滤镜链：scale/pad + subtitles。

        @param subtitle_token - 字幕滤镜路径 token（相对 ``cwd``）
        @returns 逗号连接的 vf 字符串
        """
        opts = self.options
        parts: list[str] = [
            build_scale_pad_vf(opts.width, opts.height),
            build_subtitles_vf(subtitle_token, opts.subtitle_force_style),
        ]
        if opts.extra_vf.strip():
            parts.append(opts.extra_vf.strip())
        return ",".join(parts)

    def compose(
        self,
        image_path: Path | str,
        audio_path: Path | str,
        subtitles_path: Path | str,
        output_path: Path | str,
        *,
        overwrite: bool = True,
    ) -> Path:
        """
        合成视频：图片 + 音频 + SRT → MP4。

        @param image_path - 静图（png/jpg/webp 等）
        @param audio_path - 音频（mp3/aac/wav 等）
        @param subtitles_path - SRT 字幕
        @param output_path - 输出 MP4
        @param overwrite - True 时添加 ``-y``
        @returns 输出文件绝对路径
        @raises FileNotFoundError - 输入缺失或找不到 ffmpeg
        @raises RuntimeError - ffmpeg 进程失败
        """
        image = Path(image_path).resolve()
        audio = Path(audio_path).resolve()
        subs = Path(subtitles_path).resolve()
        out = Path(output_path).resolve()

        for label, p in (("图片", image), ("音频", audio), ("字幕", subs)):
            if not p.is_file():
                raise FileNotFoundError(f"{label}文件不存在: {p}")
        assert_valid_srt_file(subs)

        out.parent.mkdir(parents=True, exist_ok=True)
        opts = self.options
        work_dir = out.parent
        sub_token, tmp_sub = resolve_subtitle_vf_token(subs, work_dir)
        vf = self.build_vf_chain(sub_token)

        cmd: list[str] = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            opts.ffmpeg_loglevel,
        ]
        if overwrite:
            cmd.append("-y")
        cmd.extend(
            [
                "-loop",
                "1",
                "-framerate",
                str(opts.fps),
                "-i",
                str(image),
                "-i",
                str(audio),
                "-vf",
                vf,
                "-c:v",
                opts.video_codec,
                "-tune",
                "stillimage",
                "-c:a",
                opts.audio_codec,
                "-b:a",
                opts.audio_bitrate,
                "-pix_fmt",
                opts.pixel_format,
                "-shortest",
                str(out),
            ]
        )

        try:
            proc = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        finally:
            if tmp_sub is not None:
                tmp_sub.unlink(missing_ok=True)

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                f"FFmpeg 合成失败（exit {proc.returncode}）\n"
                f"cwd: {work_dir}\n"
                f"命令: {' '.join(cmd)}\n"
                f"{err}"
            )
        return out

    def burn_subtitles_on_video(
        self,
        video_path: Path | str,
        subtitles_path: Path | str,
        output_path: Path | str,
        *,
        copy_audio: bool = True,
        overwrite: bool = True,
    ) -> Path:
        """
        在已有视频上烧录字幕（与用户提供的 ``ffmpeg -i video.mp4 -vf subtitles=...`` 一致）。

        @param video_path - 输入视频
        @param subtitles_path - SRT 字幕
        @param output_path - 输出视频
        @param copy_audio - True 时使用 ``-c:a copy``
        @param overwrite - True 时 ``-y``
        @returns 输出绝对路径
        """
        video = Path(video_path).resolve()
        subs = Path(subtitles_path).resolve()
        out = Path(output_path).resolve()
        if not video.is_file():
            raise FileNotFoundError(f"视频不存在: {video}")
        if not subs.is_file():
            raise FileNotFoundError(f"字幕不存在: {subs}")
        assert_valid_srt_file(subs)
        out.parent.mkdir(parents=True, exist_ok=True)

        work_dir = out.parent
        sub_token, tmp_sub = resolve_subtitle_vf_token(subs, work_dir)
        vf = build_subtitles_vf(sub_token, self.options.subtitle_force_style)
        opts = self.options
        cmd: list[str] = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            opts.ffmpeg_loglevel,
        ]
        if overwrite:
            cmd.append("-y")
        cmd.extend(["-i", str(video), "-vf", vf, "-c:v", opts.video_codec])
        if copy_audio:
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.extend(["-c:a", opts.audio_codec, "-b:a", opts.audio_bitrate])
        cmd.append(str(out))

        try:
            proc = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        finally:
            if tmp_sub is not None:
                tmp_sub.unlink(missing_ok=True)

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                f"FFmpeg 烧录字幕失败（exit {proc.returncode}）\n"
                f"cwd: {work_dir}\n"
                f"{err}"
            )
        return out


def compose_image_audio_subtitles(
    image_path: Path | str,
    audio_path: Path | str,
    subtitles_path: Path | str,
    output_path: Path | str,
    *,
    options: FfmpegComposeOptions | None = None,
    ffmpeg_bin: str | None = None,
) -> Path:
    """
    便捷函数：创建 ``FfmpegVideoComposer`` 并合成。

    @param image_path - 静图
    @param audio_path - 音频
    @param subtitles_path - SRT
    @param output_path - 输出 MP4
    @param options - 合成参数
    @param ffmpeg_bin - ffmpeg 路径
    @returns 输出绝对路径
    """
    composer = FfmpegVideoComposer(options=options, ffmpeg_bin=ffmpeg_bin)
    return composer.compose(image_path, audio_path, subtitles_path, output_path)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="FFmpeg：图片 + 音频 + SRT 字幕 → MP4（白字黑边底对齐）",
    )
    p.add_argument("-i", "--image", type=Path, required=True, help="输入图片")
    p.add_argument("-a", "--audio", type=Path, required=True, help="输入音频")
    p.add_argument("-s", "--subtitles", type=Path, required=True, help="SRT 字幕")
    p.add_argument("-o", "--output", type=Path, required=True, help="输出 MP4")
    p.add_argument("--ffmpeg", default=None, help="ffmpeg 可执行文件路径")
    p.add_argument("--width", type=int, default=1920)
    p.add_argument("--height", type=int, default=1080)
    p.add_argument("--fps", type=int, default=25)
    p.add_argument(
        "--font-name",
        default="SimHei",
        help="字幕字体（写入 force_style FontName）",
    )
    p.add_argument("--font-size", type=int, default=30)
    p.add_argument("--margin-v", type=int, default=45, help="距底边距（MarginV）")
    p.add_argument("--outline-width", type=int, default=2)
    p.add_argument(
        "--burn-only",
        type=Path,
        default=None,
        metavar="VIDEO",
        help="仅对已有视频烧录字幕（-s 必填，-i/-a 忽略）",
    )
    return p


def _force_style_from_args(args: argparse.Namespace) -> str:
    return (
        f"FontName={args.font_name},"
        f"FontSize={args.font_size},"
        f"PrimaryColour=&H00FFFFFF&,"
        f"BackColour=&H80000000&,"
        f"OutlineColour=&H00000000&,"
        f"OutlineWidth={args.outline_width},"
        f"MarginV={args.margin_v},"
        f"Alignment=2"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """
    CLI 入口。

    @param argv - 命令行参数；None 为 sys.argv[1:]
    @returns 退出码
    """
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    opts = FfmpegComposeOptions(
        width=args.width,
        height=args.height,
        fps=args.fps,
        subtitle_force_style=_force_style_from_args(args),
    )
    composer = FfmpegVideoComposer(options=opts, ffmpeg_bin=args.ffmpeg)

    try:
        if args.burn_only is not None:
            out = composer.burn_subtitles_on_video(args.burn_only, args.subtitles, args.output)
        else:
            out = composer.compose(args.image, args.audio, args.subtitles, args.output)
    except FileNotFoundError as err:
        print(str(err), file=sys.stderr)
        return 2
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 2
    except RuntimeError as err:
        print(str(err), file=sys.stderr)
        return 1

    print(f"已写入: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
