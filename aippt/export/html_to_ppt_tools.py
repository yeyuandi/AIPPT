# -*- coding: utf-8 -*-
"""
HTML→PPTX 编排入口（单模块）：``HtmlToPptCliOptions`` / ``run_html_to_ppt`` 供流水线进程内调用 ``HtmlToPptConverter``；
``StructuredTool`` 与 Pydantic 模型供 Agent ``bind_tools``。

转换实现位于同子包 ``html_to_ppt``；本文件延迟导入 ``html_to_ppt``，避免仅需 Tool schema 时加载 playwright。
"""
# 从 dataclasses 导入 dataclass
from dataclasses import dataclass
# 从 pathlib 导入 Path
from pathlib import Path

# 从 pydantic 导入 BaseModel、Field
from pydantic import BaseModel, Field

# 导入 LangChain 结构化工具
from langchain_core.tools import StructuredTool


@dataclass
class HtmlToPptCliOptions:
    """
    与 ``aippt.export.html_to_ppt.HtmlToPptConfig`` 对齐的选项（流水线 / Tool 复用）。

    @ivar fit_slide_viewport - 是否启用严格 16:9 视口
    @ivar raster_wait_ms - 截图前等待毫秒
    @ivar raster_dpr - Playwright ``device_scale_factor``（≥1）
    @ivar raster_letterbox_rgb - 视口与幻灯片宽高比不一致时 contain 留白填充 RGB
    @ivar save_slide_png - True 时在 pptx 同目录额外写入同名 ``slide_NNN.png``
    """

    fit_slide_viewport: bool = True
    raster_wait_ms: int = 1000
    raster_dpr: float = 1.0
    raster_letterbox_rgb: tuple[int, int, int] = (0xFC, 0xFB, 0xFA)
    save_slide_png: bool = False


def _options_to_config(options: HtmlToPptCliOptions):
    """
    将 CLI 选项映射为 ``HtmlToPptConfig`` 实例。

    @param options - 运行时选项
    @returns ``HtmlToPptConfig``
    """
    from .html_to_ppt import HtmlToPptConfig

    return HtmlToPptConfig(
        fit_slide_viewport=options.fit_slide_viewport,
        raster_wait_ms=int(options.raster_wait_ms),
        raster_device_scale_factor=max(1.0, float(options.raster_dpr)),
        raster_letterbox_rgb=tuple(options.raster_letterbox_rgb),
        save_slide_png=bool(options.save_slide_png),
    )


def run_html_to_ppt(
    input_html: Path,
    output_pptx: Path,
    options: HtmlToPptCliOptions | None = None,
) -> None:
    """
    进程内执行 HTML→PPTX（封装 ``HtmlToPptConverter.convert``，Playwright **``.slide`` 元素截图**）。

    @param input_html - 源 HTML
    @param output_pptx - 目标 pptx
    @param options - 可选配置；None 表示默认 16:9 视口与 DPR=1
    @raises ValueError - 参数非法
    """
    from .html_to_ppt import HtmlToPptConverter

    opts = options if options is not None else HtmlToPptCliOptions()
    cfg = _options_to_config(opts)
    HtmlToPptConverter(cfg).convert(input_html, output_pptx)


class ConvertHtmlToPptxInput(BaseModel):
    """
    ``convert_html_file_to_pptx`` 工具的输入契约（字段描述供绑定工具的 Agent 阅读）。
    """

    input_html_path: str = Field(description='本地 HTML 文件路径（根节点建议使用 class="slide"）')
    output_pptx_path: str = Field(description="输出的 .pptx 文件路径（须以 .pptx 结尾）")
    fit_slide_viewport: bool = Field(default=True, description="是否启用严格 16:9 视口（推荐 True，减少两侧露底）")
    raster_dpr: float = Field(default=1.0, ge=1.0, description="截图清晰度倍率（Playwright device_scale_factor），≥1")


def convert_html_file_to_pptx(
    input_html_path: str,
    output_pptx_path: str,
    fit_slide_viewport: bool = True,
    raster_dpr: float = 1.0,
) -> str:
    """
    调用 ``run_html_to_ppt``：把单页 HTML 转为 pptx，返回人类可读结果字符串。

    @param input_html_path - 源 HTML 路径
    @param output_pptx_path - 目标 pptx 路径
    @param fit_slide_viewport - 是否 16:9 视口
    @param raster_dpr - 截图 DPR（≥1）
    @returns 成功时返回绝对路径提示；失败返回错误说明（便于 Agent 继续推理）
    """
    validated = ConvertHtmlToPptxInput(
        input_html_path=input_html_path,
        output_pptx_path=output_pptx_path,
        fit_slide_viewport=fit_slide_viewport,
        raster_dpr=raster_dpr,
    )

    src = Path(validated.input_html_path).expanduser().resolve()
    dst = Path(validated.output_pptx_path).expanduser().resolve()
    if not src.exists():
        return f"[html_to_ppt 工具] 找不到 HTML 文件: {src}"
    if dst.suffix.lower() != ".pptx":
        return "[html_to_ppt 工具] output_pptx_path 必须以 .pptx 结尾"

    dst.parent.mkdir(parents=True, exist_ok=True)

    opts = HtmlToPptCliOptions(
        fit_slide_viewport=validated.fit_slide_viewport,
        raster_wait_ms=1000,
        raster_dpr=float(validated.raster_dpr),
    )

    try:
        run_html_to_ppt(src, dst, opts)
    except Exception as exc:  # noqa: BLE001 —— 汇总给 Agent
        return f"[html_to_ppt 工具] 转换失败: {exc}"

    return f"[html_to_ppt 工具] 已成功生成: {dst}"


def get_convert_html_to_pptx_tool() -> StructuredTool:
    """
    构造单个 LangChain ``StructuredTool``，绑定 ``convert_html_file_to_pptx``。

    @returns 可在 ``bind_tools`` / Agent 中使用的工具实例
    """
    return StructuredTool.from_function(
        func=convert_html_file_to_pptx,
        name="convert_html_file_to_pptx",
        description=(
            "Convert a local single-slide HTML file (div.slide root) to .pptx via Playwright full-viewport screenshot "
            "and python-pptx (aippt.export.html_to_ppt, in-process). "
            "中文：单页 HTML→PowerPoint（栅格页）；路径须可读写。"
        ),
        args_schema=ConvertHtmlToPptxInput,
    )


def get_html_to_ppt_tools() -> list[StructuredTool]:
    """
    返回当前包内提供的全部 html_to_ppt 相关工具列表（便于一次性绑定）。

    @returns 非空工具列表
    """
    return [get_convert_html_to_pptx_tool()]


__all__ = [
    "ConvertHtmlToPptxInput",
    "HtmlToPptCliOptions",
    "convert_html_file_to_pptx",
    "get_convert_html_to_pptx_tool",
    "get_html_to_ppt_tools",
    "run_html_to_ppt",
]
