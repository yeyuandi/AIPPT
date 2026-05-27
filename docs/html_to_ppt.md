# HTML → PPTX 导出说明

本文说明 **`aippt.export.html_to_ppt`** 如何将单页 HTML 转为单页 PPTX：Playwright 渲染页面后，**仅截取根节点 `.slide` 的边界框**，再嵌入幻灯片（内容为栅格图，**不可编辑**）。

流水线默认通过 **`html_to_ppt_tools.run_html_to_ppt`** 调用，参数与本文 **`HtmlToPptCliOptions`** / **`HtmlToPptConfig`** 对齐。

---

## 目录

1. [工作原理](#工作原理)
2. [HTML 要求](#html-要求)
3. [配置类](#配置类)
4. [命令行](#命令行)
5. [批量目录 `rerender_html_dir`](#批量目录-rerender_html_dir)
6. [编程调用](#编程调用)
7. [常见问题](#常见问题)

---

## 工作原理

```text
HTML 文件 (file://)
    → Playwright 打开页面（固定视口）
    → 定位元素 .slide
    → element.screenshot() → PNG
    → 按幻灯片尺寸 contain 贴入 pptx
```

| 概念 | 说明 |
|------|------|
| **视口** | 默认宽 **1200px**，`fit_slide_viewport=True` 时高 **675px**（16:9） |
| **幻灯片物理尺寸** | 默认宽 **7.5×16/9 英寸**、高 **7.5 英寸**（精确 16:9） |
| **截图范围** | 只有 `.slide` 内像素；`html`/`body` 留白不会进入 PPT |
| **清晰度** | `device_scale_factor`（CLI `--raster-dpr` / 流水线默认 **10**） |

与在浏览器里全屏预览的差异：HTML 若大量使用 `vw`/`vh`，在固定视口下布局可能不同，见 [faq.md](faq.md)。

---

## HTML 要求

1. 页面内应有 **一个** 用于导出的根容器，类名为 **`slide`**（流水线生成的单页 HTML 已满足）。
2. `.slide` 建议 **`overflow: hidden`**，避免内容溢出被裁切时难以察觉。
3. 外链资源（Bootstrap CDN、图片）需可被 Playwright 加载；本地 `file://` 相对路径资源相对于 HTML 文件解析。
4. 单屏无滚动条：提示词与 `aippt/prompts/` 中的 raster 布局约束一致。

---

## 配置类

### `HtmlToPptConfig`（`html_to_ppt.py`）

| 字段 | 默认 | 说明 |
|------|------|------|
| `slide_width_in` | `7.5×16/9` | 幻灯片宽度（英寸） |
| `slide_height_in` | `7.5` | 幻灯片高度（英寸） |
| `viewport_width` | `1200` | Playwright 视口宽（px） |
| `viewport_height` | `750` | 视口高；`fit_slide_viewport=True` 时被覆盖 |
| `fit_slide_viewport` | `False`（CLI/流水线常为 `True`） | 视口高 = round(宽×9/16) |
| `raster_wait_ms` | `1000` | 截图前等待（ms） |
| `raster_device_scale_factor` | `1.0` | 截图 DPR，流水线常用 `10` |
| `raster_letterbox_rgb` | `(252,251,250)` | contain 留白填充色 |
| `save_slide_png` | `False` | 是否额外写同名 `.png` |

### `HtmlToPptCliOptions`（`html_to_ppt_tools.py`）

流水线 / Web 导出使用的简化选项，映射到 `HtmlToPptConfig`：

| 字段 | 流水线默认 | 说明 |
|------|------------|------|
| `fit_slide_viewport` | `True` | 严格 16:9 视口 |
| `raster_wait_ms` | `1000` | 截图前等待 |
| `raster_dpr` | `10` | 清晰度倍率 |
| `save_slide_png` | `False` | 额外 PNG |

---

## 命令行

### 单文件：`python -m aippt.export.html_to_ppt`

```bash
python -m aippt.export.html_to_ppt path/to/slide_000.html \
  --fit-slide-viewport \
  --raster-dpr 10 \
  --raster-wait-ms 1000
```

| 参数 | 说明 |
|------|------|
| `input_html` | 输入 HTML 路径 |
| `-o` / `--output` | 输出 pptx；默认与 HTML 同主名 |
| `--slide-width` / `--slide-height` | 幻灯片尺寸（英寸） |
| `--viewport-width` / `--viewport-height` | 浏览器视口（px） |
| `--fit-slide-viewport` | 16:9 视口，推荐开启 |
| `--raster-wait-ms` | 截图前等待 |
| `--raster-dpr` | `device_scale_factor`，默认 **1**（单文件 CLI）；流水线为 **10** |
| `--save-slide-png` | 额外输出同名 PNG |

省略 `-o` 时，在 HTML 同目录生成 `slide_000.pptx`。

---

## 批量目录 `rerender_html_dir`

```bash
# 对某次运行目录下所有 slide_NNN.html 重截图并合并
python -m aippt.export.rerender_html_dir output_run/my_deck --merge --raster-dpr 10

# 仅按 deck_outline.json 合并已有 pptx（不启动浏览器）
python -m aippt.export.rerender_html_dir output_run/my_deck --merge-only

# 只处理指定页
python -m aippt.export.rerender_html_dir output_run/my_deck --only slide_000.html slide_002.html --merge
```

| 参数 | 说明 |
|------|------|
| `html_dir` | 含 `*.html` 的目录 |
| `--only` | 只处理列出的相对路径（顺序即合并顺序） |
| `--recursive` | 递归子目录 |
| `--include-deck-template` | 包含 `deck_template.html`（默认跳过） |
| `--merge` | 转换后按处理顺序合并为一个 pptx |
| `--merge-only` | 不截图，仅合并已有 pptx |
| `--outline-file` | `--merge-only` 用的大纲 JSON |
| `--append-unlisted` | 大纲外其余 pptx 追加在后 |
| `--merged-output` | 合并输出路径 |
| `--no-fit-slide-viewport` | 关闭 16:9 视口（默认开启 fit） |
| `--raster-dpr` | 默认 **10** |

`--merge` 与 `--merge-only` **互斥**。

---

## 编程调用

### 进程内（推荐）

```python
from pathlib import Path
from aippt.export.html_to_ppt_tools import HtmlToPptCliOptions, run_html_to_ppt

run_html_to_ppt(
    Path("output_run/demo/slide_000.html"),
    Path("output_run/demo/slide_000.pptx"),
    HtmlToPptCliOptions(
        fit_slide_viewport=True,
        raster_dpr=10.0,
        raster_wait_ms=1000,
        save_slide_png=False,
    ),
)
```

### 转换器类

```python
from pathlib import Path
from aippt.export.html_to_ppt import HtmlToPptConfig, HtmlToPptConverter

converter = HtmlToPptConverter(
    HtmlToPptConfig(fit_slide_viewport=True, raster_device_scale_factor=10.0)
)
converter.convert(Path("slide.html"), Path("out.pptx"))
```

### 合并多页

```python
from pathlib import Path
from aippt.export.merge_pptx import merge_pptx_files, resolve_pptx_paths_from_deck_outline

paths = resolve_pptx_paths_from_deck_outline(Path("output_run/demo"))
merge_pptx_files(paths, Path("output_run/demo/merged.pptx"))
```

### LangChain Tool

```python
from aippt.export.html_to_ppt_tools import get_convert_html_to_pptx_tool, get_html_to_ppt_tools
```

---

## 常见问题

| 问题 | 建议 |
|------|------|
| `playwright` 未安装浏览器 | `python -m playwright install chromium` |
| 幻灯片四周细白边 | 开启 `--fit-slide-viewport`；检查幻灯片宽高比是否与视口一致 |
| 底部文字被裁切 | 减少单页内容；检查 `.slide { overflow:hidden }` 与 prompts 布局 |
| 合并后某页空白 | 复杂 OLE/图表未完整支持；确认图片 rId 映射（见 `merge_pptx.py`） |
| 单文件 CLI 默认 DPR=1 偏糊 | 手动加 `--raster-dpr 10`，或与流水线一致 |

更多排错见 [faq.md](faq.md)。
