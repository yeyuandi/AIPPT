# -*- coding: utf-8 -*-
"""命令行入口：读取文档 → LangChain（Ollama / DeepSeek）→ **deck 模板 HTML** → 多页 HTML（封面 + **目录** + 正文复用模板）→ Playwright **``.slide`` 区域截图** html_to_ppt → 合并 pptx。"""
# 导入 argparse 用于解析终端参数
import argparse
# 导入 os 以便写入 LLM_PROVIDER 覆盖环境
import os
# 导入 sys 以便 stderr / argv
import sys
# 导入 Path 处理文件路径
from pathlib import Path

# 导入默认工作目录与仓库根路径常量（相对导入）
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

def main(argv: list[str] | None = None) -> int:
    """
    主流程：解析参数、调用模型、写 HTML、转 pptx、合并。

    @param argv - 可选自定义参数列表；None 表示使用 sys.argv[1:]
    @returns 进程退出码（0 成功）
    """
    parser = argparse.ArgumentParser(
        description="LangChain +（Ollama / DeepSeek）+ html_to_ppt：Playwright **``.slide`` 元素截图**导出 pptx",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(DEFAULT_SAMPLE_INPUT),
        help="输入文档路径（.txt / .md / .docx），默认 samples/sample_input.txt",
    )
    parser.add_argument(
        "--work-dir",
        type=str,
        default=str(DEFAULT_WORKDIR),
        help="输出根目录，默认仓库根目录 output_run；若解析后与默认 output_run 根相同则实际写入 output_run/<输入文档主文件名>/（与示例脚本一致）。其它路径则直接使用。**若目标目录已存在会先整目录清空再写入。**",
    )
    parser.add_argument(
        "--max-slides",
        type=int,
        default=None,
        help="大纲页数上限；省略则由模型根据全文自行推理页数（脚本另有硬上限以防异常过长）",
    )
    parser.add_argument(
        "--target-slides",
        type=int,
        default=None,
        metavar="N",
        help="大纲页数软目标（写入提示词）；模型尽量接近 N 页但不得超过 --max-slides（若指定）；勿大于 max-slides",
    )
    parser.add_argument("--skip-merge", action="store_true", help="跳过合并，仅生成单页 pptx")
    parser.add_argument(
        "--raster-dpr",
        type=float,
        default=10.0,
        help="截图清晰度：Playwright device_scale_factor（≥1），默认 10",
    )
    parser.add_argument(
        "--save-slide-png",
        action="store_true",
        help="在每张 slide_NNN.pptx 同目录额外写入 slide_NNN.png（与嵌入幻灯片的栅格一致）",
    )
    parser.add_argument(
        "--html-style",
        type=str,
        default="",
        help="可选：风格描述（写入 HTML 提示词；须符合单屏无滚动条等截图导出约束）",
    )
    parser.add_argument(  # 命令行临时切换后端（等价设置环境变量 LLM_PROVIDER）
        "--llm-provider",
        choices=("ollama", "deepseek"),
        default=None,
        help="对话后端：ollama（默认）或 deepseek（OpenAPI）；不设则读环境变量 LLM_PROVIDER",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])  # 解析命令行得到 Namespace 对象

    slides_err = validate_outline_slides_cli(args.max_slides, args.target_slides)
    if slides_err is not None:
        print(slides_err, file=sys.stderr)
        return 1

    if args.llm_provider is not None:  # 若用户通过 CLI 显式指定提供方
        os.environ["LLM_PROVIDER"] = args.llm_provider  # 写入进程环境供 get_llm_provider() 读取

    input_path = Path(args.input).expanduser().resolve()  # 解析输入文档绝对路径
    if not input_path.exists():  # 若文件不存在则报错退出
        print(f"找不到输入文件: {input_path}", file=sys.stderr)  # 错误信息输出到 stderr
        return 1  # 返回非零退出码表示失败

    try:
        doc_text = load_document_text(input_path)  # 按后缀分支读取 UTF-8 文本或 docx 抽取
    except Exception as err:  # docx 损坏、编码异常、依赖缺失等均归入可读错误
        print(f"读取输入失败: {err}", file=sys.stderr)  # 统一错误出口
        return 1  # 非零退出
    if not doc_text:  # 若正文为空则无需调用模型
        print("输入文档为空", file=sys.stderr)  # 打印提示到 stderr
        return 1  # 返回失败码

    work_dir_arg = Path(args.work_dir).expanduser().resolve()  # 用户给出的输出目录
    default_run_root = DEFAULT_WORKDIR.expanduser().resolve()
    if work_dir_arg == default_run_root:  # 未自定义到具体子目录时，按文档名独占子文件夹，避免清空整个 output_run
        work_dir = DEFAULT_WORKDIR / safe_output_run_subdir_name(input_path.stem)
    else:
        work_dir = work_dir_arg
    prepare_clean_output_dir(work_dir)  # 已存在则删除目录及其中全部文件后再创建

    auth_err = provider_auth_error_message()  # 根据 LLM_PROVIDER 检查密钥是否齐全
    if auth_err is not None:  # 若有返回则说明配置不可用
        print(auth_err, file=sys.stderr, end="")  # 将中文指引写到 stderr（末尾自带换行）
        return 1  # 非零退出码提示调用方检查环境

    cli_provider = args.llm_provider if args.llm_provider else None
    outline = invoke_outline_chain(
        doc_text,
        max_slides=args.max_slides,
        target_slides=args.target_slides,
        provider=cli_provider,
    )

    raw_outline_pages = len(outline.slides)
    cap_outline_pages(outline, args.max_slides)
    if args.max_slides is None and raw_outline_pages > OUTLINE_AUTO_PAGES_HARD_CAP:
        print(
            f"注意：模型返回 {raw_outline_pages} 页，已超过脚本硬上限 {OUTLINE_AUTO_PAGES_HARD_CAP}，"
            f"已截取前 {OUTLINE_AUTO_PAGES_HARD_CAP} 页。",
            file=sys.stderr,
            flush=True,
        )

    assign_slide_output_filenames(outline)  # 每页 deck_outline.json 写入 html_file / pptx_file

    outline_plain = format_deck_outline_plain(outline)
    outline_json_path = work_dir / "deck_outline.json"
    outline_txt_path = work_dir / "deck_outline.txt"
    outline_json_path.write_text(deck_outline_to_json(outline), encoding="utf-8")
    outline_txt_path.write_text(outline_plain, encoding="utf-8")
    n_pages = len(outline.slides)
    print(f"大纲共 {n_pages} 页，将生成 {n_pages} 页 pptx。", flush=True)
    print(
        f"大纲已保存（全文见文件）: {outline_json_path.resolve()} | {outline_txt_path.resolve()}",
        flush=True,
    )

    html_llm = build_chat_llm(provider=cli_provider, json_mode=False)
    style_sec = format_html_style_hints_section(args.html_style)

    deck_template_chain = build_deck_html_template_chain(html_llm)
    title_html_chain = build_raster_title_slide_chain(html_llm)
    toc_html_chain = build_raster_toc_slide_chain(html_llm)
    content_html_chain = build_raster_content_slide_chain(html_llm)

    pptx_paths: list[Path] = []

    dpr = max(1.0, float(args.raster_dpr))
    ppt_opts = HtmlToPptCliOptions(
        fit_slide_viewport=True,
        raster_wait_ms=1000,
        raster_dpr=dpr,
        save_slide_png=bool(args.save_slide_png),
    )

    tpl_vars = deck_template_prompt_vars(outline, doc_text, style_sec)
    tpl_prompt_path = work_dir / "deck_template_llm_prompt.txt"
    tpl_prompt_path.write_text(
        format_html_slide_prompt_dump(
            variables=tpl_vars,
            chain_kind="deck_template",
        ),
        encoding="utf-8",
    )
    print(f"deck 模板 HTML 提示词: {tpl_prompt_path}")
    deck_template_html = deck_template_chain.invoke(tpl_vars)
    deck_template_path = work_dir / DECK_TEMPLATE_HTML_FILENAME
    deck_template_path.write_text(deck_template_html, encoding="utf-8")
    print(f"已写入整套样式模板: {deck_template_path.resolve()}", flush=True)

    # 按大纲顺序生成 HTML（slides[0] 封面；不少于 3 页时 slides[1] 为目录；其后为正文）
    has_toc = len(outline.slides) >= 3
    for idx, slide in enumerate(outline.slides):
        if idx == 0:
            vars_html = title_slide_prompt_vars(slide, deck_template_html, style_sec)
            chain_kind = "title"
            slide_chain = title_html_chain
        elif has_toc and idx == 1:
            vars_html = toc_slide_prompt_vars(slide, outline, deck_template_html, style_sec)
            chain_kind = "toc"
            slide_chain = toc_html_chain
        else:
            vars_html = content_slide_prompt_vars(slide, deck_template_html, style_sec)
            chain_kind = "content"
            slide_chain = content_html_chain
        llm_prompt_path = work_dir / f"slide_{idx:03d}_llm_prompt.txt"
        llm_prompt_path.write_text(
            format_html_slide_prompt_dump(
                variables=vars_html,
                chain_kind=chain_kind,
            ),
            encoding="utf-8",
        )
        print(f"第 {idx + 1} 页 HTML 提示词: {llm_prompt_path}")
        html_doc = slide_chain.invoke(vars_html)
        html_path = work_dir / f"slide_{idx:03d}.html"  # 生成顺序编号的 HTML 文件名（三位补零）
        html_path.write_text(html_doc, encoding="utf-8")  # 将字符串写入磁盘 UTF-8 编码

        pptx_path = work_dir / f"slide_{idx:03d}.pptx"  # 生成与 HTML 同索引的 pptx 文件名
        run_html_to_ppt(html_path, pptx_path, ppt_opts)
        pptx_paths.append(pptx_path.resolve())  # 收集绝对路径供合并函数使用
        print(f"已生成第 {idx + 1} 页: {pptx_path}")  # 打印进度信息便于观察流水线执行状态

    if not args.skip_merge and pptx_paths:  # 若未跳过合并且存在至少一页 pptx
        merged_path = work_dir / merged_deck_pptx_filename(input_path.stem)
        merge_pptx_files(pptx_paths, merged_path)  # 调用合并工具写入汇总演示文稿
        print(f"已合并: {merged_path}")  # 打印合并后的路径提示用户打开查看

    return 0  # 全流程成功则返回 0


if __name__ == "__main__":  # 当被 python 直接执行该文件时（不推荐，优先 python -m）
    raise SystemExit(main())  # 将 main 返回值作为进程退出码抛出
