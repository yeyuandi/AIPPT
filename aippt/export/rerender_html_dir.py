# -*- coding: utf-8 -*-
"""
将指定目录内的 HTML 幻灯片批量重新转为单页 PPTX（与 HTML 同目录、同主文件名），可选按顺序合并为一个文件。

用法示例::

    python -m aippt.export.rerender_html_dir path/to/slides --merge --raster-dpr 10
    python -m aippt.export.rerender_html_dir path/to/slides --only slide_000.html slide_001.html
    python -m aippt.export.rerender_html_dir path/to/slides --merge-only
"""
# 从 __future__ 导入注解语法
from __future__ import annotations

# 导入 argparse 解析 CLI
import argparse
# 导入 sys 用于 stderr 与退出码
import sys
# 导入 Path 处理路径
from pathlib import Path

# 导入合并稿文件名生成与时间戳命名
from ..config import merged_deck_pptx_filename
# 导入合并实现与按大纲解析 pptx 顺序
from .merge_pptx import merge_pptx_files, resolve_pptx_paths_from_deck_outline
# 导入截图转换内核配置与转换器
from .html_to_ppt import (
    DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX,
    DEFAULT_SLIDE_HEIGHT_IN,
    DEFAULT_SLIDE_WIDTH_IN,
    HtmlToPptConfig,
    HtmlToPptConverter,
)


def _collect_html_paths(
    directory: Path,
    *,
    only_names: list[str] | None,
    include_deck_template: bool,
    recursive: bool,
) -> list[Path]:
    """
    解析待处理的 HTML 路径列表（均已 resolve）。

    @param directory - 用户指定的根目录
    @param only_names - 非空时仅处理相对该目录的这些文件名（保留 CLI 顺序）；None 表示目录内枚举
    @param include_deck_template - False 时跳过名为 deck_template.html 的文件
    @param recursive - True 时使用 rglob 递归子目录
    @returns 非空路径列表；若无匹配则返回空列表
    """
    root = directory.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    if only_names:
        out: list[Path] = []
        for name in only_names:
            p = (root / name).expanduser().resolve()
            if not p.is_file():
                msg = f"找不到 HTML 文件: {p}"
                raise FileNotFoundError(msg)
            if p.suffix.lower() != ".html":
                msg = f"不是 HTML 文件: {p}"
                raise ValueError(msg)
            if not include_deck_template and p.name.lower() == "deck_template.html":
                continue
            out.append(p)
        return out

    pattern = "**/*.html" if recursive else "*.html"
    paths = sorted(root.glob(pattern), key=lambda x: str(x).lower())
    if not include_deck_template:
        paths = [p for p in paths if p.name.lower() != "deck_template.html"]
    return paths


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """
    解析命令行参数。

    @param argv - 一般为 sys.argv[1:]
    @returns 解析后的 Namespace
    """
    parser = argparse.ArgumentParser(
        description="批量将目录内 HTML 重新导出为同目录下的 .pptx，可选合并为一个演示文稿",
    )
    parser.add_argument(
        "html_dir",
        type=Path,
        help="包含若干 *.html 的目录路径",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="REL",
        default=None,
        help="仅处理相对于 html_dir 的文件名（保留所列顺序）；省略则处理目录内全部匹配的 *.html",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="递归子目录查找 *.html（默认仅在 html_dir 顶层查找）",
    )
    parser.add_argument(
        "--include-deck-template",
        action="store_true",
        help="包含 deck_template.html（默认跳过整套模板参考页）",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="全部转换完成后，按处理顺序合并为一个 .pptx（另见 --merged-output）；与 --merge-only 互斥",
    )
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="不执行 HTML 截图；仅按 deck_outline.json 中 slides[].pptx_file 顺序合并目录内已有 .pptx（默认仍写入带时间戳的合并文件名，见 --merged-output）",
    )
    parser.add_argument(
        "--outline-file",
        type=Path,
        default=None,
        help="（仅 --merge-only）大纲 JSON；默认 <html_dir>/deck_outline.json",
    )
    parser.add_argument(
        "--append-unlisted",
        action="store_true",
        help="（仅 --merge-only）在大纲顺序之后追加目录内未列入大纲的其它 *.pptx（文件名排序）",
    )
    parser.add_argument(
        "--merged-output",
        type=Path,
        default=None,
        help="合并输出路径（须以 .pptx 结尾）；默认写入 html_dir 下带时间戳的文件名",
    )
    parser.add_argument(
        "--slide-width",
        type=float,
        default=DEFAULT_SLIDE_WIDTH_IN,
        help=f"幻灯片宽度（英寸），默认 {DEFAULT_SLIDE_WIDTH_IN:.6g}",
    )
    parser.add_argument(
        "--slide-height",
        type=float,
        default=DEFAULT_SLIDE_HEIGHT_IN,
        help=f"幻灯片高度（英寸），默认 {DEFAULT_SLIDE_HEIGHT_IN:g}",
    )
    parser.add_argument(
        "--viewport-width",
        type=int,
        default=DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX,
        help=f"浏览器视口宽度（像素），默认 {DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX}",
    )
    parser.add_argument(
        "--viewport-height",
        type=int,
        default=750,
        help="浏览器视口高度（像素）；启用默认的严格 16:9 视口时该值会被覆盖",
    )
    parser.set_defaults(fit_slide_viewport=True)
    parser.add_argument(
        "--no-fit-slide-viewport",
        action="store_false",
        dest="fit_slide_viewport",
        help="关闭严格 16:9 视口，改用 --viewport-height",
    )
    parser.add_argument(
        "--raster-wait-ms",
        type=int,
        default=1000,
        metavar="MS",
        help="截图前等待毫秒，默认 1000",
    )
    parser.add_argument(
        "--raster-dpr",
        type=float,
        default=10.0,
        metavar="FACTOR",
        help="Playwright device_scale_factor（≥1），默认 10（与主流水线一致）",
    )
    parser.add_argument(
        "--save-slide-png",
        action="store_true",
        help="每张 pptx 同目录额外写入同名 .png",
    )
    return parser.parse_args(argv)


def _merged_output_path(html_dir: Path, merged_output: Path | None) -> Path:
    """
    解析合并稿输出路径（默认带时间戳文件名）。

    @param html_dir - 运行目录（resolve 后的文件夹）
    @param merged_output - 用户指定输出；None 表示默认
    @returns 合并 .pptx 的绝对路径
    @raises ValueError - 扩展名不是 .pptx
    """
    root = html_dir
    if merged_output is not None:
        merged = merged_output.expanduser().resolve()
        if merged.suffix.lower() != ".pptx":
            msg = "--merged-output 须以 .pptx 结尾"
            raise ValueError(msg)
        return merged
    stem = root.name if root.name else "deck"
    return root / merged_deck_pptx_filename(stem)


def main(argv: list[str] | None = None) -> int:
    """
    CLI 入口：批量 HTML→PPTX，可选合并。

    @param argv - 可选参数列表；None 表示 sys.argv[1:]
    @returns 进程退出码；0 成功，1 失败
    """
    raw = sys.argv[1:] if argv is None else argv
    args = _parse_args(raw)

    if args.merge and args.merge_only:
        print("请只选用其一：--merge（先截图再合并）或 --merge-only（仅合并）", file=sys.stderr)
        return 1

    root = args.html_dir.expanduser().resolve()
    if not root.is_dir():
        print(f"不是目录: {root}", file=sys.stderr)
        return 1

    if args.merge_only:
        if args.only is not None:
            print("--merge-only 时不要使用 --only", file=sys.stderr)
            return 1
        try:
            merged = _merged_output_path(root, args.merged_output)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        outline = (
            args.outline_file.expanduser().resolve()
            if args.outline_file is not None
            else root / "deck_outline.json"
        )
        try:
            pptx_paths = resolve_pptx_paths_from_deck_outline(
                root,
                outline,
                append_unlisted=bool(args.append_unlisted),
                output_path=merged,
            )
        except (OSError, ValueError, FileNotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        try:
            merge_pptx_files(pptx_paths, merged)
        except Exception as exc:  # noqa: BLE001
            print(f"合并失败: {exc}", file=sys.stderr)
            return 1
        print(f"已合并 {len(pptx_paths)} 个文件 -> {merged.resolve()}", flush=True)
        return 0

    try:
        html_paths = _collect_html_paths(
            args.html_dir,
            only_names=list(args.only) if args.only is not None else None,
            include_deck_template=bool(args.include_deck_template),
            recursive=bool(args.recursive),
        )
    except (OSError, ValueError, FileNotFoundError, NotADirectoryError) as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    if not html_paths:
        print("未找到待处理的 HTML（检查目录、--only、或是否被 deck_template 过滤）", file=sys.stderr)
        return 1

    cfg = HtmlToPptConfig(
        slide_width_in=float(args.slide_width),
        slide_height_in=float(args.slide_height),
        viewport_width=int(args.viewport_width),
        viewport_height=int(args.viewport_height),
        fit_slide_viewport=bool(args.fit_slide_viewport),
        raster_wait_ms=max(0, int(args.raster_wait_ms)),
        raster_device_scale_factor=max(1.0, float(args.raster_dpr)),
        save_slide_png=bool(args.save_slide_png),
    )
    converter = HtmlToPptConverter(cfg)

    pptx_paths: list[Path] = []
    for html_path in html_paths:
        out_pptx = html_path.with_suffix(".pptx")
        try:
            converter.convert(html_path, out_pptx)
        except Exception as exc:  # noqa: BLE001 —— CLI 汇总错误
            print(f"转换失败 {html_path}: {exc}", file=sys.stderr)
            return 1
        pptx_paths.append(out_pptx.resolve())
        print(f"已写入: {out_pptx.resolve()}", flush=True)

    if args.merge:
        try:
            merged = _merged_output_path(root, args.merged_output)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        try:
            merge_pptx_files(pptx_paths, merged)
        except Exception as exc:  # noqa: BLE001
            print(f"合并失败: {exc}", file=sys.stderr)
            return 1
        print(f"已合并: {merged.resolve()}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
