# -*- coding: utf-8 -*-
"""
示例流水线：文档 → 大纲 → **deck 模板 HTML** → 逐页 HTML（封面 + **目录** + 正文复用模板）→ Playwright **``.slide`` 区域截图**写入 pptx → 合并。

运行前请在仓库根目录配置好 ``.env``（或 ``aippt/.env``）：Ollama 云端填 ``OLLAMA_API_KEY``；DeepSeek OpenAPI 填 ``DEEPSEEK_API_KEY`` 且 ``LLM_PROVIDER=deepseek``。

常用参数::

    --raster-dpr    Playwright device_scale_factor（≥1），默认 10
    --html-style    可选，风格描述（须符合截图导出约束）
    --max-slides    可选页数硬上限；省略则由模型规划（脚本内有硬上限）
    --target-slides 可选页数软目标（写入大纲提示词）

运行（建议在仓库根目录）::

    python -m aippt.example_invoke
    python -m aippt.example_invoke --raster-dpr 10 --input path/to/材料.docx
    python -m aippt.example_invoke --html-style "浅色商务，主色点缀" --input samples/材料.docx
"""
# 导入 argparse，用于解析终端参数
import argparse
# 导入 os，用于设置 LLM_PROVIDER 覆盖环境
import os
# 导入 sys，用于 stderr / 退出码
import sys
# 导入 Path，用于拼接输出文件路径
from pathlib import Path
# 导入默认输出目录与包路径（加载 .env 的副作用在此模块内完成）
from aippt.config import (
    DEFAULT_SAMPLE_INPUT,
    DEFAULT_WORKDIR,
    OUTLINE_AUTO_PAGES_HARD_CAP,
    merged_deck_pptx_filename,
    prepare_clean_output_dir,
    provider_auth_error_message,
    safe_output_run_subdir_name,
)
from aippt.chains import (
    DECK_TEMPLATE_HTML_FILENAME,
    build_deck_html_template_chain,
    build_raster_content_slide_chain,
    build_raster_toc_slide_chain,
    build_raster_title_slide_chain,
    content_slide_prompt_vars,
    deck_template_prompt_vars,
    format_html_slide_prompt_dump,
    format_html_style_hints_section,
    title_slide_prompt_vars,
    toc_slide_prompt_vars,
    validate_outline_slides_cli,
)
from aippt.domain import assign_slide_output_filenames, deck_outline_to_json, format_deck_outline_plain
from aippt.export.html_to_ppt_tools import HtmlToPptCliOptions, run_html_to_ppt
from aippt.export.merge_pptx import merge_pptx_files
from aippt.io import load_document_text
from aippt.llm import build_chat_llm
from aippt.services.outline import cap_outline_pages, invoke_outline_chain


_EXAMPLE_PROGRESS_TAG = "[示例]"


def _example_progress(message: str) -> None:
    """
    打印示例流水线进度（stdout，立即刷新）。

    @param message - 单行说明
    @returns None
    """
    print(f"{_EXAMPLE_PROGRESS_TAG} {message}", flush=True)


def parse_example_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    解析示例脚本的命令行参数。

    @param argv - 传入参数列表；None 表示使用 ``sys.argv[1:]``
    @returns 解析后的 Namespace
    """
    parser = argparse.ArgumentParser(
        description="示例：文档 → 大纲 → HTML（截图导出约束）→ `.slide` 区域截图 pptx → 合并",
    )
    parser.add_argument(
        "--raster-dpr",
        type=float,
        default=10.0,
        help="Playwright device_scale_factor（≥1），默认 10",
    )
    parser.add_argument(
        "--save-slide-png",
        action="store_true",
        help="导出每张 pptx 时在旁写入同名 PNG（slide_NNN.png）",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(DEFAULT_SAMPLE_INPUT),
        help="输入文档路径（.txt / .md / .docx），默认 samples/sample_input.txt",
    )
    parser.add_argument(
        "--max-slides",
        type=int,
        default=None,
        help="大纲页数上限；省略则由模型根据全文自行规划页数（脚本内另有硬上限以防过长）",
    )
    parser.add_argument(
        "--target-slides",
        type=int,
        default=None,
        metavar="N",
        help="大纲页数软目标（写入提示词）；尽量接近 N 页且不得超过 --max-slides（若指定）",
    )
    parser.add_argument(
        "--html-style",
        type=str,
        default="",
        help="可选：风格/氛围描述（写入提示词；须符合截图导出约束）",
    )
    parser.add_argument(
        "--llm-provider",
        choices=("ollama", "deepseek"),
        default=None,
        help="ollama（默认）或 deepseek；不传则读环境变量 LLM_PROVIDER",
    )
    return parser.parse_args(argv if argv is not None else sys.argv[1:])


def run_example(
    *,
    input_path: str,
    raster_dpr: float = 10.0,
    max_slides: int | None = None,
    target_slides: int | None = None,
    html_style: str = "",
    save_slide_png: bool = False,
    llm_provider: str | None = None,
) -> None:
    """
    演示完整链路：文档（txt/md/docx）→ 概要大纲 → 逐页 HTML → 截图 pptx → 合并。

    @param input_path - 输入文件路径字符串
    @param raster_dpr - Playwright 截图清晰度倍率（≥1）
    @param max_slides - 大纲页数上限；None 表示由模型规划页数
    @param target_slides - 大纲页数软目标；None 表示不写入提示词
    @param html_style - 可选，风格偏好（自然语言）
    @param save_slide_png - 是否在每页 pptx 旁写入同名 PNG
    @returns None
    """
    auth_err = provider_auth_error_message()
    if auth_err is not None:
        print(auth_err, file=sys.stderr, end="")
        raise SystemExit(1)

    DEFAULT_WORKDIR.mkdir(parents=True, exist_ok=True)

    src = Path(input_path).expanduser().resolve()
    if not src.exists():
        print(f"找不到输入文件: {src}", file=sys.stderr)
        raise SystemExit(1)
    try:
        document = load_document_text(src)
    except Exception as err:
        print(f"读取输入失败: {err}", file=sys.stderr)
        raise SystemExit(1)
    if not document.strip():
        print("输入文档为空", file=sys.stderr)
        raise SystemExit(1)

    sub_dir = safe_output_run_subdir_name(src.stem)
    work_dir = DEFAULT_WORKDIR / sub_dir
    prepare_clean_output_dir(work_dir)  # ``output_run/文档名`` 已存在则清空后重建

    _example_progress(
        f"[1/6] 已读取文档：{src.name}（约 {len(document)} 字符）；"
        f"输出目录：{work_dir}（含 deck_template.html + slide_NNN.html / .pptx）"
    )

    cli_provider = llm_provider
    _example_progress("[2/6] 正在调用大纲模型…")
    outline = invoke_outline_chain(
        document,
        max_slides=max_slides,
        target_slides=target_slides,
        provider=cli_provider,
    )

    raw_len = len(outline.slides)
    cap_outline_pages(outline, max_slides)

    capped_note = ""
    if max_slides is None and raw_len > OUTLINE_AUTO_PAGES_HARD_CAP:
        capped_note = (
            f"（模型返回 {raw_len} 页，已超过脚本硬上限 {OUTLINE_AUTO_PAGES_HARD_CAP}，"
            f"已截取前 {OUTLINE_AUTO_PAGES_HARD_CAP} 页）"
        )

    final_n = len(outline.slides)
    mode_desc = "由模型根据全文规划页数" if max_slides is None else f"用户上限 {max_slides}"
    tgt = f"；软目标 {target_slides}" if target_slides is not None else ""
    outline_msg = f"[3/6] 大纲完成：将生成 {final_n} 页（{mode_desc}{tgt}）；模型原始返回 {raw_len} 页"
    if capped_note:
        outline_msg += capped_note
    _example_progress(outline_msg)

    assign_slide_output_filenames(outline)  # deck_outline.json 每页含 html_file / pptx_file

    outline_plain = format_deck_outline_plain(outline)
    outline_json_path = work_dir / "deck_outline.json"
    outline_txt_path = work_dir / "deck_outline.txt"
    outline_json_path.write_text(deck_outline_to_json(outline), encoding="utf-8")
    outline_txt_path.write_text(outline_plain, encoding="utf-8")
    _example_progress(f"[大纲] 已写入 {outline_json_path.name}、{outline_txt_path.name}")

    html_llm = build_chat_llm(provider=cli_provider, json_mode=False)
    style_sec = format_html_style_hints_section(html_style)
    if style_sec.strip():
        _example_progress("[提示] 已附加 --html-style 到模板与各页 HTML 提示词")

    deck_template_chain = build_deck_html_template_chain(html_llm)
    title_html_chain = build_raster_title_slide_chain(html_llm)
    toc_html_chain = build_raster_toc_slide_chain(html_llm)
    content_html_chain = build_raster_content_slide_chain(html_llm)

    tpl_vars = deck_template_prompt_vars(outline, document, style_sec)
    tpl_prompt_path = work_dir / "deck_template_llm_prompt.txt"
    tpl_prompt_path.write_text(
        format_html_slide_prompt_dump(
            variables=tpl_vars,
            chain_kind="deck_template",
        ),
        encoding="utf-8",
    )
    _example_progress(f"[4/6] 正在生成整套样式模板 → {DECK_TEMPLATE_HTML_FILENAME} …")
    deck_template_html = deck_template_chain.invoke(tpl_vars)
    deck_template_path = work_dir / DECK_TEMPLATE_HTML_FILENAME
    deck_template_path.write_text(deck_template_html, encoding="utf-8")
    _example_progress(f"[4/6] 模板已写入 {deck_template_path.name}；提示词见 {tpl_prompt_path.name}")

    dpr = max(1.0, float(raster_dpr))
    ppt_opts = HtmlToPptCliOptions(
        fit_slide_viewport=True,
        raster_wait_ms=1000,
        raster_dpr=dpr,
        save_slide_png=save_slide_png,
    )

    pptx_paths: list[Path] = []
    has_toc = len(outline.slides) >= 3
    for idx, slide in enumerate(outline.slides):
        if idx == 0:
            vars_html = title_slide_prompt_vars(slide, deck_template_html, style_sec)
            chain_kind = "title"
            slide_chain = title_html_chain
            phase = "封面"
        elif has_toc and idx == 1:
            vars_html = toc_slide_prompt_vars(slide, outline, deck_template_html, style_sec)
            chain_kind = "toc"
            slide_chain = toc_html_chain
            phase = "目录"
        else:
            vars_html = content_slide_prompt_vars(slide, deck_template_html, style_sec)
            chain_kind = "content"
            slide_chain = content_html_chain
            phase = "正文"
        _example_progress(
            f"[5/6·{idx + 1}/{final_n}] 第 {idx + 1} 页（{phase}）：调用模型生成 HTML …"
        )
        llm_prompt_path = work_dir / f"slide_{idx:03d}_llm_prompt.txt"
        llm_prompt_path.write_text(
            format_html_slide_prompt_dump(
                variables=vars_html,
                chain_kind=chain_kind,
            ),
            encoding="utf-8",
        )
        _example_progress(f"[5/6·{idx + 1}/{final_n}] 第 {idx + 1} 页：LLM 提示词已写入 → {llm_prompt_path.name}")
        html_doc = slide_chain.invoke(vars_html)
        base_name = f"slide_{idx:03d}"
        html_path = work_dir / f"{base_name}.html"
        html_path.write_text(html_doc, encoding="utf-8")
        _example_progress(f"[5/6·{idx + 1}/{final_n}] 第 {idx + 1} 页：HTML → PPTX …")
        pptx_path = work_dir / f"{base_name}.pptx"
        run_html_to_ppt(html_path, pptx_path, ppt_opts)
        pptx_paths.append(pptx_path.resolve())
        _example_progress(f"[5/6·{idx + 1}/{final_n}] 第 {idx + 1} 页：已完成 → {pptx_path.name}")

    _example_progress("[6/6] 正在合并演示文稿 …")
    merged_path = work_dir / merged_deck_pptx_filename(src.stem)
    merge_pptx_files(pptx_paths, merged_path)
    _example_progress(f"[6/6] 合并完成（共 {final_n} 页）：{merged_path}")


def main(argv: list[str] | None = None) -> int:
    """
    命令行入口：解析参数后执行示例流水线。

    @param argv - 可选自定义参数列表
    @returns 进程退出码
    """
    args = parse_example_args(argv if argv is not None else sys.argv[1:])
    if args.llm_provider is not None:
        os.environ["LLM_PROVIDER"] = args.llm_provider
    slides_err = validate_outline_slides_cli(args.max_slides, args.target_slides)
    if slides_err is not None:
        print(slides_err, file=sys.stderr)
        return 1
    run_example(
        input_path=args.input,
        raster_dpr=args.raster_dpr,
        max_slides=args.max_slides,
        target_slides=args.target_slides,
        html_style=args.html_style,
        save_slide_png=bool(args.save_slide_png),
        llm_provider=args.llm_provider,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
