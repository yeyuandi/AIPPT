#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 Playwright 将 HTML 幻灯片 **``.slide`` 元素区域**截图后写入 PPTX（python-pptx）；内容为栅格图，文字不可编辑。

依赖：pip install playwright python-pptx；首次使用 Chromium：python -m playwright install chromium

说明：默认同目录输出 .pptx；可选将 ``.slide`` 截图**额外**写入与 pptx 同主名的 ``.png``（如 ``slide_000.png``）。幻灯片根节点建议使用 class="slide"。视口用于渲染布局；**截图仅包含 `.slide` 元素的像素边界**，不把 slide 外的 html/body 留白一并写入 PPT。

对**固定 Playwright 视口**内渲染的页面，使用 Playwright **元素截图**截取 ``.slide`` 边界框为 PNG，再按幻灯片尺寸等比缩放（contain）、不拉伸变形。
默认幻灯片宽 ``DEFAULT_SLIDE_WIDTH_IN``（= 7.5×16/9 英寸）与高 ``DEFAULT_SLIDE_HEIGHT_IN``（7.5 英寸）为**精确 16:9**，与默认视口宽高比一致；若 `.slide` 未铺满视口，PNG 尺寸随元素收缩，contain 时可能出现 letterbox。
建议配合 ``fit_slide_viewport=True`` 使 `.slide` 通常铺满视口；本地预览 HTML 时请使用与 ``HtmlToPptConfig.viewport_width`` 一致的响应式尺寸
（默认宽 ``DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX``，高为 round(宽×9/16)），避免大量使用 vw/vh 导致与固定视口不一致。
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# 默认 Playwright 视口宽度（CSS 像素）；配合 ``fit_slide_viewport=True`` 时高度为 ``round(宽×9/16)``，严格 16:9。
DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX: int = 1200

# 幻灯片物理尺寸（英寸）：须与 CSS 视口 **严格 16:9** 一致。
# 使用 ``13.333`` 等浮点字面量换算 EMU 时易与 ``7.5`` 形成微小宽高比偏差，``contain`` 贴图会留细边，幻灯片观感像被缩小。
DEFAULT_SLIDE_HEIGHT_IN: float = 7.5
DEFAULT_SLIDE_WIDTH_IN: float = 7.5 * 16.0 / 9.0


def default_playwright_viewport_height_px(*, width_px: int | None = None) -> int:
    """
    与 ``HtmlToPptConfig.effective_viewport_height`` 在 fit 模式下一致的 16:9 高度（像素）。

    @param width_px - 视口宽度；None 表示使用 ``DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX``
    @returns 高度，至少为 1
    """
    w = DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX if width_px is None else int(width_px)
    return max(1, int(round(w * 9 / 16)))


@dataclass
class HtmlToPptConfig:
    """
    HTML → PPTX 转换的可复用配置（固定 Playwright「``.slide`` 元素截图」路径）。

    @param slide_width_in - 导出幻灯片宽度（英寸），默认与 ``DEFAULT_SLIDE_WIDTH_IN`` 一致（精确 16:9）
    @param slide_height_in - 导出幻灯片高度（英寸），默认 ``DEFAULT_SLIDE_HEIGHT_IN``
    @param viewport_width - Playwright 视口宽度（CSS 像素）
    @param viewport_height - Playwright 视口高度；若 fit_slide_viewport 为 True 则会被覆盖为 round(宽×9/16)
    @param fit_slide_viewport - True 时使用严格 16:9 视口，使 .slide 横向铺满、不露 html 衬底
    @param raster_wait_ms - 截图前额外等待毫秒（字体/布局）
    @param raster_device_scale_factor - Playwright device_scale_factor，>1 可提高截图清晰度
    @param raster_letterbox_rgb - 视口与幻灯片宽高比不一致时，幻灯片衬底 RGB（contain 留白填充）
    @param save_slide_png - True 时在输出 pptx 同目录写入同名 ``.png``（与嵌入 pptx 的像素一致）
    """

    slide_width_in: float = DEFAULT_SLIDE_WIDTH_IN
    slide_height_in: float = DEFAULT_SLIDE_HEIGHT_IN
    viewport_width: int = DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX
    viewport_height: int = 750
    fit_slide_viewport: bool = False
    raster_wait_ms: int = 1000
    raster_device_scale_factor: float = 1.0
    raster_letterbox_rgb: tuple[int, int, int] = (0xFC, 0xFB, 0xFA)
    save_slide_png: bool = False

    def effective_viewport_height(self) -> int:
        """
        返回实际用于 Playwright 的视口高度。

        @returns 视口高度（像素，至少为 1）
        """
        if self.fit_slide_viewport:
            return max(1, int(round(self.viewport_width * 9 / 16)))
        return self.viewport_height


class HtmlToPptConverter:
    """
    将本地 HTML（根容器 ``div.slide``）经 **``.slide`` 元素截图**转为 .pptx 的可实例化工具类。

    @example
    converter = HtmlToPptConverter(HtmlToPptConfig(fit_slide_viewport=True))
    converter.convert(Path("slide.html"), Path("out.pptx"))
    """

    def __init__(self, config: HtmlToPptConfig | None = None) -> None:
        """
        @param config - 转换默认配置；为 None 时使用 HtmlToPptConfig() 默认实例
        """
        self.config = config if config is not None else HtmlToPptConfig()

    def convert(
        self,
        input_html: Path | str,
        output_pptx: Path | str | None = None,
        *,
        images_dir: Path | str | None = None,
    ) -> Path:
        """
        执行 HTML → PPTX 转换（``.slide`` 区域栅格截图）。

        @param input_html - 源 HTML 路径
        @param output_pptx - 输出 .pptx；None 时与 HTML 同目录同名 .pptx
        @param images_dir - 保留签名兼容，截图路径不使用（忽略）
        @returns 解析后的输出文件绝对路径
        @raises FileNotFoundError - HTML 不存在
        @raises ValueError - 输出扩展名不是 .pptx
        @raises ImportError - 未安装 playwright / python-pptx 时由下层抛出
        """
        del images_dir  # 截图由浏览器渲染页面，相对资源随 HTML 路径解析；无需单独基准目录
        input_path = Path(input_html).expanduser().resolve()
        if output_pptx is None:
            out_path = input_path.with_suffix(".pptx")
        else:
            out_path = Path(output_pptx).expanduser().resolve()

        return _convert_raster_slide_core(
            input_path,
            out_path,
            slide_width_in=self.config.slide_width_in,
            slide_height_in=self.config.slide_height_in,
            viewport_width=self.config.viewport_width,
            viewport_height=self.config.effective_viewport_height(),
            raster_wait_ms=self.config.raster_wait_ms,
            raster_device_scale_factor=self.config.raster_device_scale_factor,
            letterbox_rgb=self.config.raster_letterbox_rgb,
            save_slide_png=self.config.save_slide_png,
        )


def html_to_pptx(
    input_html: Path,
    output_pptx: Path,
    *,
    slide_width_in: float = DEFAULT_SLIDE_WIDTH_IN,
    slide_height_in: float = DEFAULT_SLIDE_HEIGHT_IN,
    viewport_width: int = DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX,
    viewport_height: int = 750,
    fit_slide_viewport: bool = False,
    raster_wait_ms: int = 1000,
    raster_device_scale_factor: float = 1.0,
    raster_letterbox_rgb: tuple[int, int, int] = (0xFC, 0xFB, 0xFA),
    save_slide_png: bool = False,
) -> Path:
    """
    函数式封装：等价于使用 HtmlToPptConfig + HtmlToPptConverter 进行一次转换。

    @param input_html - 源 HTML 文件路径
    @param output_pptx - 输出 .pptx 路径
    @param slide_width_in - 幻灯片宽度（英寸）
    @param slide_height_in - 幻灯片高度（英寸）
    @param viewport_width - Playwright 视口宽
    @param viewport_height - Playwright 视口高（fit_slide_viewport 为 True 时被推算值覆盖）
    @param fit_slide_viewport - 是否使用严格 16:9 视口高度
    @param raster_wait_ms - 截图前等待毫秒
    @param raster_device_scale_factor - 截图清晰度倍率
    @param raster_letterbox_rgb - contain 模式下留白填充 RGB
    @param save_slide_png - 是否在 pptx 旁写入同名 PNG
    @returns 输出路径
    """
    cfg = HtmlToPptConfig(
        slide_width_in=slide_width_in,
        slide_height_in=slide_height_in,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        fit_slide_viewport=fit_slide_viewport,
        raster_wait_ms=raster_wait_ms,
        raster_device_scale_factor=raster_device_scale_factor,
        raster_letterbox_rgb=raster_letterbox_rgb,
        save_slide_png=save_slide_png,
    )
    return HtmlToPptConverter(cfg).convert(input_html, output_pptx)


def _png_dimensions_from_bytes(buf: bytes) -> tuple[int, int]:
    """
    从 PNG 二进制读取 IHDR 宽高（无需 Pillow）。

    @param buf - PNG 完整字节
    @returns (width_px, height_px)
    """
    sig = b"\x89PNG\r\n\x1a\n"
    if len(buf) < 24 or buf[:8] != sig:
        msg = "无效的 PNG 截图数据"
        raise ValueError(msg)
    if buf[12:16] != b"IHDR":
        msg = "PNG 缺少 IHDR"
        raise ValueError(msg)
    w_px, h_px = struct.unpack(">II", buf[16:24])
    return w_px, h_px


def _screenshot_slide_element_png(
    html_path: Path,
    *,
    viewport_width: int,
    viewport_height: int,
    raster_wait_ms: int,
    raster_device_scale_factor: float,
) -> bytes:
    """
    使用 Playwright 在固定视口内渲染页面后，**仅截取** ``.slide`` 元素的 PNG（不包含 slide 以外的视口区域）。

    @param html_path - 本地 HTML 绝对路径
    @param viewport_width - 视口宽（CSS 像素）
    @param viewport_height - 视口高（CSS 像素）
    @param raster_wait_ms - `goto` 后额外等待毫秒
    @param raster_device_scale_factor - device_scale_factor（≥1）
    @returns PNG 字节；页面须含 ``.slide`` 根容器
    """
    from playwright.sync_api import sync_playwright

    resolved = html_path.resolve()
    if not resolved.exists():
        msg = f"未找到 HTML 文件: {resolved}"
        raise FileNotFoundError(msg)

    dpr = max(1.0, float(raster_device_scale_factor))
    wait_ms = max(0, int(raster_wait_ms))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
                device_scale_factor=dpr,
            )
            page = context.new_page()
            page.goto(resolved.as_uri())
            page.wait_for_timeout(wait_ms)
            slide_el = page.query_selector(".slide")
            if slide_el is None:
                msg = "页面中未找到 .slide，无法截图（请保证根内容为 <div class=\"slide\">）"
                raise RuntimeError(msg)
            # 仅截取 `.slide` 边界框，不把 slide 外的 html/body 留白写入 PNG。
            slide_el.scroll_into_view_if_needed()
            return slide_el.screenshot(type="png")
        finally:
            browser.close()


def _convert_raster_slide_core(
    input_html: Path,
    output_pptx: Path,
    *,
    slide_width_in: float,
    slide_height_in: float,
    viewport_width: int,
    viewport_height: int,
    raster_wait_ms: int,
    raster_device_scale_factor: float,
    letterbox_rgb: tuple[int, int, int],
    save_slide_png: bool = False,
) -> Path:
    """
    将网页幻灯片区域截图作为单张图片铺满幻灯片（等比 contain，必要时长宽比与幻灯片一致时可完全铺满）。

    @param input_html - 已 resolve 的 HTML 路径
    @param output_pptx - 已 resolve 的输出路径
    @returns output_pptx
    """
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Emu

    if not input_html.exists():
        msg = f"未找到 HTML 文件: {input_html}"
        raise FileNotFoundError(msg)

    if output_pptx.suffix.lower() != ".pptx":
        raise ValueError(
            "仅生成 .pptx，请将输出路径扩展名设为 .pptx",
        )

    png_bytes = _screenshot_slide_element_png(
        input_html,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        raster_wait_ms=raster_wait_ms,
        raster_device_scale_factor=raster_device_scale_factor,
    )
    if save_slide_png:
        png_sidecar = output_pptx.with_suffix(".png")
        png_sidecar.write_bytes(png_bytes)
    w_px, h_px = _png_dimensions_from_bytes(png_bytes)
    if w_px < 1 or h_px < 1:
        msg = f"截图尺寸无效: {w_px}×{h_px}"
        raise ValueError(msg)

    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        tmp_path = Path(tmp_name)
        tmp_path.write_bytes(png_bytes)

        prs = Presentation()
        prs.slide_width = Emu(int(slide_width_in * 914400))
        prs.slide_height = Emu(int(slide_height_in * 914400))
        slide_layout_blank = 6
        slide = prs.slides.add_slide(prs.slide_layouts[slide_layout_blank])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(*letterbox_rgb)

        sw = int(prs.slide_width)
        sh = int(prs.slide_height)
        img_ar = w_px / h_px
        slide_ar = sw / sh
        if abs(img_ar - slide_ar) < 1e-4:
            pic_w, pic_h = sw, sh
            left = 0
            top = 0
        else:
            scale = min(sw / w_px, sh / h_px)
            pic_w = int(round(scale * w_px))
            pic_h = int(round(scale * h_px))
            left = (sw - pic_w) // 2
            top = (sh - pic_h) // 2

        slide.shapes.add_picture(str(tmp_path), left, top, width=pic_w, height=pic_h)
        prs.save(str(output_pptx))
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    return output_pptx


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """
    解析命令行参数。

    @param argv - 通常为 sys.argv[1:]
    @returns 解析后的 Namespace
    """
    parser = argparse.ArgumentParser(
        description="HTML 转 PPTX：Playwright 截取 `.slide` 元素写入单页幻灯片（栅格、不可编辑）",
    )
    parser.add_argument(
        "input_html",
        type=Path,
        help="输入的 HTML 文件路径",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="输出 .pptx 路径；默认与 HTML 同目录同名 .pptx",
    )
    parser.add_argument(
        "--slide-width",
        type=float,
        default=DEFAULT_SLIDE_WIDTH_IN,
        help=f"幻灯片宽度（英寸），默认 {DEFAULT_SLIDE_WIDTH_IN:.6g}（与默认视口 16:9 精确匹配）",
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
        default=1200,
        help="浏览器视口宽度（像素），默认 1200",
    )
    parser.add_argument(
        "--viewport-height",
        type=int,
        default=750,
        help="浏览器视口高度（像素）；与 --fit-slide-viewport 同时使用时以推算高度为准",
    )
    parser.add_argument(
        "--fit-slide-viewport",
        action="store_true",
        help="将视口高度设为 round(宽度×9/16)，严格 16:9，使 .slide 铺满视口、避免两侧 html 背景露边",
    )
    parser.add_argument(
        "--raster-wait-ms",
        type=int,
        default=1000,
        metavar="MS",
        help="截图前等待毫秒（字体/动画），默认 1000",
    )
    parser.add_argument(
        "--raster-dpr",
        type=float,
        default=1.0,
        metavar="FACTOR",
        help="截图清晰度倍率 Playwright device_scale_factor（≥1），默认 1",
    )
    parser.add_argument(
        "--save-slide-png",
        action="store_true",
        help="在输出的 .pptx 同目录额外写入同名 .png（与嵌入幻灯片的栅格一致）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    命令行入口。

    @param argv - 可选参数列表；为 None 时使用 sys.argv[1:]
    @returns 进程退出码：0 成功；1 失败
    """
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    input_html: Path = args.input_html
    output_pptx: Path = (
        args.output
        if args.output is not None
        else input_html.with_suffix(".pptx")
    )

    config = HtmlToPptConfig(
        slide_width_in=args.slide_width,
        slide_height_in=args.slide_height,
        viewport_width=args.viewport_width,
        viewport_height=args.viewport_height,
        fit_slide_viewport=args.fit_slide_viewport,
        raster_wait_ms=args.raster_wait_ms,
        raster_device_scale_factor=max(1.0, float(args.raster_dpr)),
        save_slide_png=bool(args.save_slide_png),
    )

    try:
        HtmlToPptConverter(config).convert(input_html, output_pptx)
    except ImportError:
        print(
            "未找到所需依赖：请 pip install playwright python-pptx，并安装 Chromium：python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI 需要汇总错误信息
        print(f"转换失败: {exc}", file=sys.stderr)
        return 1

    print(f"已生成: {output_pptx}")
    return 0


__all__ = [
    "DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX",
    "DEFAULT_SLIDE_HEIGHT_IN",
    "DEFAULT_SLIDE_WIDTH_IN",
    "HtmlToPptConfig",
    "HtmlToPptConverter",
    "html_to_pptx",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
