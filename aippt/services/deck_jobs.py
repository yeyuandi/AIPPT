# -*- coding: utf-8 -*-
"""
Web 向导分步编排（上传 → 大纲 → deck 模板 → 逐页 HTML → 截图 pptx → 合并）。

产物写入 ``output_run/web_jobs/<job_id>/``；进度见 ``progress.json``。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from werkzeug.utils import secure_filename

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
)
from aippt.config import merged_deck_pptx_filename, provider_auth_error_message
from aippt.io import load_document_text
from aippt.domain import (
    DeckOutline,
    assign_slide_output_filenames,
    deck_outline_to_json,
    format_deck_outline_plain,
)
from aippt.export.html_to_ppt_tools import HtmlToPptCliOptions, run_html_to_ppt
from aippt.export.merge_pptx import merge_pptx_files
from aippt.llm import build_chat_llm
from aippt.services.job_store import (
    MAX_WIZARD_RESTORE_DOCUMENT_CHARS,
    allowed_upload_extensions,
    atomic_write_json,
    create_job,
    read_meta,
    read_progress,
    resolve_job_dir,
    web_jobs_root,
    write_meta,
)
from aippt.services.outline import cap_outline_pages, invoke_outline_chain, meta_llm_provider

_MERGE_EXTRA_MARKER = "\n\n--- 附加输入内容 ---\n\n"


def save_slide_html(job_id: str, slide_index: int, html: str) -> str:
    """
    将向导中编辑后的单页 HTML 写回任务目录。

    @param job_id - 任务 UUID
    @param slide_index - 页索引（从 0 起）
    @param html - 完整 HTML 源码
    @returns 文件名（例如 ``slide_000.html``）
    """
    job_dir = resolve_job_dir(job_id)
    if slide_index < 0:
        raise ValueError("slide_index 须 ≥ 0")
    name = f"slide_{slide_index:03d}.html"
    path = job_dir / name
    if not path.is_file():
        raise FileNotFoundError(f"缺少 {name}，请先完成该页 HTML 生成")
    path.write_text(html, encoding="utf-8")
    return name


def save_deck_outline_files(job_id: str, payload: dict[str, Any]) -> tuple[DeckOutline, str]:
    """
    校验前端提交的 JSON 并写回 ``deck_outline.json`` / ``deck_outline.txt``。

    @param job_id - 任务 UUID
    @param payload - 与 ``DeckOutline`` 结构一致的对象
    @returns (校验后的大纲, 可读纯文本)
    """
    job_dir = resolve_job_dir(job_id)
    deck = DeckOutline.model_validate(payload)
    assign_slide_output_filenames(deck)
    outline_plain = format_deck_outline_plain(deck)
    outline_json_str = deck_outline_to_json(deck)
    (job_dir / "deck_outline.json").write_text(outline_json_str, encoding="utf-8")
    (job_dir / "deck_outline.txt").write_text(outline_plain, encoding="utf-8")
    return deck, outline_plain


def save_document_source(
    job_id: str,
    storage,
    extra_text: str | None,
    llm_provider: str | None,
) -> dict[str, Any]:
    """
    写入任务正文：支持仅上传文件、仅文本框，或二者合并。

    @param job_id - 任务 ID
    @param storage - Werkzeug FileStorage；无文件时 None
    @param extra_text - 用户粘贴正文
    @param llm_provider - ollama/deepseek，可选
    @returns 预览与字符数等
    """
    job_dir = resolve_job_dir(job_id)
    text_extra = (extra_text or "").strip()
    has_file = storage is not None and bool(getattr(storage, "filename", None))
    allowed = allowed_upload_extensions()

    if not has_file and not text_extra:
        raise ValueError("请上传文稿文件或在输入框中填写正文")
    if not has_file and len(text_extra) < 5:
        raise ValueError("未上传文件时，正文至少输入 5 个字")

    segments: list[str] = []
    stem = "manual-input"
    original_filename = ""

    if has_file:
        raw_name = storage.filename or "document"
        original_filename = raw_name
        suffix = Path(raw_name.strip()).suffix.lower()
        if suffix not in allowed:
            raise ValueError(f"不支持的文件类型：仅允许 {', '.join(sorted(allowed))}")
        safe = secure_filename(raw_name) or "document"
        dest = job_dir / f"input{suffix}"
        storage.save(str(dest))
        try:
            doc_from_file = load_document_text(dest)
        except Exception as err:
            raise ValueError(f"解析文档失败：{err}") from err
        if not (doc_from_file or "").strip():
            raise ValueError("上传文件解析后正文为空")
        segments.append(doc_from_file.strip())
        stem_from_safe = Path(safe).stem if Path(safe).suffix else ""
        stem = stem_from_safe or Path(raw_name).stem or "document"

    if text_extra:
        if segments:
            segments.append(_MERGE_EXTRA_MARKER)
        segments.append(text_extra)

    doc_text = "".join(segments).strip()
    if not doc_text:
        raise ValueError("合并后正文为空")

    if has_file and text_extra:
        source_summary = "已合并：上传文件与输入框内容"
    elif has_file:
        source_summary = "来源：上传文件"
    else:
        source_summary = "来源：输入框文本"

    (job_dir / "document.txt").write_text(doc_text, encoding="utf-8")
    meta = {
        "stem": stem,
        "original_filename": original_filename or "(文本输入)",
        "raster_dpr": 10.0,
        "max_slides": None,
        "target_slides": None,
        "llm_provider": (llm_provider or "").strip().lower() or None,
        "html_style": "",
        "save_slide_png": False,
    }
    write_meta(job_dir, meta)
    atomic_write_json(job_dir / "progress.json", {"phase": "parsed", "message": "正文已抽取"})
    preview_len = 1200
    return {
        "stem": stem,
        "char_count": len(doc_text),
        "preview": doc_text[:preview_len],
        "truncated": len(doc_text) > preview_len,
        "source_summary": source_summary,
    }


def run_outline_step(job_id: str, max_slides: int | None, target_slides: int | None) -> dict[str, Any]:
    """
    调用 LLM 生成大纲并落盘。

    @param job_id - 任务 ID
    @param max_slides - 覆盖 meta 上限
    @param target_slides - 软目标
    @returns outline_plain、outline_json、slide_count
    """
    job_dir = resolve_job_dir(job_id)
    doc_path = job_dir / "document.txt"
    if not doc_path.is_file():
        raise FileNotFoundError("缺少 document.txt，请先加载文档内容")
    doc_text = doc_path.read_text(encoding="utf-8")
    meta = read_meta(job_dir)
    eff_max = max_slides if max_slides is not None else meta.get("max_slides")
    eff_target = target_slides if target_slides is not None else meta.get("target_slides")
    if eff_max is not None:
        eff_max = int(eff_max)
    if eff_target is not None:
        eff_target = int(eff_target)

    meta.update({"max_slides": eff_max, "target_slides": eff_target})
    write_meta(job_dir, meta)

    provider = meta_llm_provider(meta)
    outline = invoke_outline_chain(
        doc_text,
        max_slides=eff_max,
        target_slides=eff_target,
        provider=provider,
    )
    cap_outline_pages(outline, eff_max)
    assign_slide_output_filenames(outline)
    outline_plain = format_deck_outline_plain(outline)
    outline_json_str = deck_outline_to_json(outline)
    (job_dir / "deck_outline.json").write_text(outline_json_str, encoding="utf-8")
    (job_dir / "deck_outline.txt").write_text(outline_plain, encoding="utf-8")

    atomic_write_json(
        job_dir / "progress.json",
        {"phase": "outline_done", "slide_count": len(outline.slides), "message": "大纲已生成"},
    )
    return {
        "outline_plain": outline_plain,
        "outline_json": json.loads(outline_json_str),
        "slide_count": len(outline.slides),
    }


def run_deck_template_step(job_id: str, html_style: str) -> dict[str, Any]:
    """
    生成整套 deck 模板 HTML。

    @param job_id - 任务 ID
    @param html_style - 风格描述
    @returns 字符长度与文件名
    """
    job_dir = resolve_job_dir(job_id)
    meta = read_meta(job_dir)
    auth = provider_auth_error_message(meta_llm_provider(meta))
    if auth is not None:
        raise RuntimeError(auth.strip())
    doc_text = (job_dir / "document.txt").read_text(encoding="utf-8")
    outline_path = job_dir / "deck_outline.json"
    if not outline_path.is_file():
        raise FileNotFoundError("缺少 deck_outline.json")
    outline = DeckOutline.model_validate_json(outline_path.read_text(encoding="utf-8"))

    meta["html_style"] = html_style or ""
    write_meta(job_dir, meta)

    html_llm = build_chat_llm(provider=meta_llm_provider(meta), json_mode=False)
    deck_template_chain = build_deck_html_template_chain(html_llm)
    style_sec = format_html_style_hints_section(html_style)
    tpl_vars = deck_template_prompt_vars(outline, doc_text, style_sec)
    tpl_prompt_path = job_dir / "deck_template_llm_prompt.txt"
    tpl_prompt_path.write_text(
        format_html_slide_prompt_dump(variables=tpl_vars, chain_kind="deck_template"),
        encoding="utf-8",
    )
    deck_template_html = deck_template_chain.invoke(tpl_vars)

    out_html = job_dir / DECK_TEMPLATE_HTML_FILENAME
    out_html.write_text(deck_template_html, encoding="utf-8")
    atomic_write_json(
        job_dir / "progress.json",
        {"phase": "template_done", "message": "deck 模板 HTML 已生成"},
    )
    return {"html_length": len(deck_template_html), "filename": DECK_TEMPLATE_HTML_FILENAME}


def _generate_all_slide_htmls(job_dir: Path, meta: dict[str, Any]) -> None:
    """在后台线程中生成全部 slide_NNN.html。"""
    outline = DeckOutline.model_validate_json((job_dir / "deck_outline.json").read_text(encoding="utf-8"))
    deck_template_html = (job_dir / DECK_TEMPLATE_HTML_FILENAME).read_text(encoding="utf-8")
    html_style = meta.get("html_style") or ""
    style_sec = format_html_style_hints_section(html_style)

    html_llm = build_chat_llm(provider=meta_llm_provider(meta), json_mode=False)
    title_html_chain = build_raster_title_slide_chain(html_llm)
    toc_html_chain = build_raster_toc_slide_chain(html_llm)
    content_html_chain = build_raster_content_slide_chain(html_llm)

    has_toc = len(outline.slides) >= 3
    total = len(outline.slides)
    try:
        for idx, slide in enumerate(outline.slides):
            if idx == 0:
                vars_html = title_slide_prompt_vars(slide, deck_template_html, style_sec)
                chain_kind = "title"
                slide_chain = title_html_chain
                phase_label = "封面"
            elif has_toc and idx == 1:
                vars_html = toc_slide_prompt_vars(slide, outline, deck_template_html, style_sec)
                chain_kind = "toc"
                slide_chain = toc_html_chain
                phase_label = "目录"
            else:
                vars_html = content_slide_prompt_vars(slide, deck_template_html, style_sec)
                chain_kind = "content"
                slide_chain = content_html_chain
                phase_label = "正文"

            atomic_write_json(
                job_dir / "progress.json",
                {
                    "phase": "slides_running",
                    "current": idx + 1,
                    "total": total,
                    "message": f"正在生成第 {idx + 1}/{total} 页（{phase_label}）：{slide.title[:40]}",
                },
            )
            llm_prompt_path = job_dir / f"slide_{idx:03d}_llm_prompt.txt"
            llm_prompt_path.write_text(
                format_html_slide_prompt_dump(variables=vars_html, chain_kind=chain_kind),
                encoding="utf-8",
            )
            html_doc = slide_chain.invoke(vars_html)
            html_path = job_dir / f"slide_{idx:03d}.html"
            html_path.write_text(html_doc, encoding="utf-8")

        atomic_write_json(
            job_dir / "progress.json",
            {"phase": "slides_done", "total": total, "message": "全部页面 HTML 已生成"},
        )
    except Exception as err:
        atomic_write_json(
            job_dir / "progress.json",
            {"phase": "error", "message": f"生成页面 HTML 失败：{err}"},
        )
        raise


def start_slide_html_generation(job_id: str, app_obj: Any) -> None:
    """
    异步启动逐页 HTML 生成（守护线程）。

    @param job_id - 任务 ID
    @param app_obj - Flask app（application context）
    """
    job_dir = resolve_job_dir(job_id)
    prog = read_progress(job_dir)
    if prog.get("phase") == "slides_running":
        raise RuntimeError("页面生成正在进行中")
    if prog.get("phase") == "slides_done":
        return

    if not (job_dir / DECK_TEMPLATE_HTML_FILENAME).is_file():
        raise FileNotFoundError("请先生成 deck 模板")

    meta = read_meta(job_dir)

    def worker():
        with app_obj.app_context():
            try:
                _generate_all_slide_htmls(job_dir, meta)
            except Exception as err:
                atomic_write_json(
                    job_dir / "progress.json",
                    {"phase": "error", "message": f"生成页面 HTML 失败：{err}"},
                )

    threading.Thread(target=worker, daemon=True).start()


def _export_pptx_and_merge(job_dir: Path, meta: dict[str, Any]) -> None:
    """逐页 HTML→pptx 并合并。"""
    outline = DeckOutline.model_validate_json((job_dir / "deck_outline.json").read_text(encoding="utf-8"))
    stem = meta.get("stem") or "document"
    dpr = float(meta.get("raster_dpr") or 10)
    ppt_opts = HtmlToPptCliOptions(
        fit_slide_viewport=True,
        raster_wait_ms=1000,
        raster_dpr=max(1.0, dpr),
        save_slide_png=bool(meta.get("save_slide_png")),
    )
    total = len(outline.slides)
    pptx_paths: list[Path] = []
    for idx in range(total):
        html_path = job_dir / f"slide_{idx:03d}.html"
        pptx_path = job_dir / f"slide_{idx:03d}.pptx"
        if not html_path.is_file():
            raise FileNotFoundError(f"缺少 {html_path.name}")
        atomic_write_json(
            job_dir / "progress.json",
            {
                "phase": "pptx_running",
                "current": idx + 1,
                "total": total,
                "message": f"正在导出第 {idx + 1}/{total} 页 pptx（Playwright）",
            },
        )
        run_html_to_ppt(html_path, pptx_path, ppt_opts)
        pptx_paths.append(pptx_path.resolve())

    merged_name = merged_deck_pptx_filename(stem)
    merged_path = job_dir / merged_name
    merge_pptx_files(pptx_paths, merged_path)
    atomic_write_json(
        job_dir / "progress.json",
        {
            "phase": "pptx_done",
            "merged_filename": merged_name,
            "message": "已合并演示文稿",
        },
    )


def start_export_pptx(
    job_id: str,
    app_obj: Any,
    raster_dpr: float | None = None,
    save_slide_png: bool | None = None,
) -> None:
    """
    异步启动 pptx 导出与合并。

    @param job_id - 任务 ID
    @param app_obj - Flask app 实例
    @param raster_dpr - 截图倍率
    @param save_slide_png - 是否额外保存 PNG
    """
    job_dir = resolve_job_dir(job_id)
    prog = read_progress(job_dir)
    if prog.get("phase") == "pptx_running":
        raise RuntimeError("PPTX 导出正在进行中")

    outline_path = job_dir / "deck_outline.json"
    if not outline_path.is_file():
        raise FileNotFoundError("缺少大纲文件")
    outline = DeckOutline.model_validate_json(outline_path.read_text(encoding="utf-8"))
    for idx in range(len(outline.slides)):
        if not (job_dir / f"slide_{idx:03d}.html").is_file():
            raise FileNotFoundError(f"缺少 slide_{idx:03d}.html，请先完成页面 HTML 生成")

    if prog.get("phase") == "pptx_done":
        atomic_write_json(
            job_dir / "progress.json",
            {
                "phase": "slides_done",
                "total": len(outline.slides),
                "message": "准备重新导出 PPTX",
            },
        )

    meta = read_meta(job_dir)
    meta_changed = False
    if raster_dpr is not None:
        meta["raster_dpr"] = max(1.0, float(raster_dpr))
        meta_changed = True
    if save_slide_png is not None:
        meta["save_slide_png"] = bool(save_slide_png)
        meta_changed = True
    if meta_changed:
        write_meta(job_dir, meta)

    def worker():
        with app_obj.app_context():
            try:
                _export_pptx_and_merge(job_dir, read_meta(job_dir))
            except Exception as err:
                atomic_write_json(
                    job_dir / "progress.json",
                    {"phase": "error", "message": f"PPTX 导出失败：{err}"},
                )

    threading.Thread(target=worker, daemon=True).start()


def list_job_summaries() -> list[dict[str, Any]]:
    """
    列出可载入的历史 Web 任务。

    @returns 按修改时间倒序的摘要列表
    """
    root = web_jobs_root()
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for p in root.iterdir():
        if not p.is_dir() or not (p / "document.txt").is_file():
            continue
        jid = p.name
        try:
            resolve_job_dir(jid)
        except ValueError:
            continue
        try:
            meta = read_meta(p)
            prog = read_progress(p)
            st = p.stat()
        except (json.JSONDecodeError, OSError):
            continue
        items.append(
            {
                "job_id": jid,
                "mtime": st.st_mtime,
                "phase": prog.get("phase") or "unknown",
                "stem": meta.get("stem") or jid[:8],
                "original_filename": meta.get("original_filename") or "",
                "message": str(prog.get("message") or ""),
            }
        )
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def wizard_restore_bundle(job_id: str) -> dict[str, Any]:
    """
    组装从历史任务恢复向导所需的数据。

    @param job_id - 任务 UUID
    @returns 可 JSON 序列化的字典
    """
    job_dir = resolve_job_dir(job_id)
    doc_path = job_dir / "document.txt"
    if not doc_path.is_file():
        raise FileNotFoundError("缺少 document.txt，无法载入该任务")
    doc_text = doc_path.read_text(encoding="utf-8")
    if len(doc_text) > MAX_WIZARD_RESTORE_DOCUMENT_CHARS:
        raise ValueError(
            f"正文超过 {MAX_WIZARD_RESTORE_DOCUMENT_CHARS} 字符，暂不支持从历史任务载入向导"
        )
    meta = read_meta(job_dir)
    prog = read_progress(job_dir)
    preview_len = 1200
    outline_json: Any = None
    outline_plain: str | None = None
    oj = job_dir / "deck_outline.json"
    ot = job_dir / "deck_outline.txt"
    if oj.is_file():
        try:
            outline_json = json.loads(oj.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            outline_json = None
    if ot.is_file():
        try:
            outline_plain = ot.read_text(encoding="utf-8")
        except OSError:
            outline_plain = None
    has_outline = outline_json is not None
    has_template = (job_dir / DECK_TEMPLATE_HTML_FILENAME).is_file()
    phase = str(prog.get("phase") or "")
    slides_phase_complete = phase in ("slides_done", "pptx_running", "pptx_done")
    pptx_complete = phase == "pptx_done"
    slide_count = 0
    if isinstance(outline_json, dict):
        slides = outline_json.get("slides")
        if isinstance(slides, list):
            slide_count = len(slides)
    orig_fn = meta.get("original_filename")
    source_summary = f"历史任务载入 · {orig_fn or 'document.txt'}"
    return {
        "job_id": job_id,
        "progress": prog,
        "meta": meta,
        "document": {
            "text": doc_text,
            "char_count": len(doc_text),
            "preview": doc_text[:preview_len],
            "truncated": len(doc_text) > preview_len,
            "source_summary": source_summary,
        },
        "outline_json": outline_json,
        "outline_plain": outline_plain,
        "slide_count": slide_count,
        "hints": {
            "has_outline": has_outline,
            "has_template": has_template,
            "slides_phase_complete": slides_phase_complete,
            "pptx_complete": pptx_complete,
        },
    }


def merged_pptx_path(job_id: str) -> Path | None:
    """
    @param job_id - 任务 ID
    @returns 合并稿路径；未完成时 None
    """
    job_dir = resolve_job_dir(job_id)
    prog = read_progress(job_dir)
    if prog.get("phase") != "pptx_done":
        return None
    name = prog.get("merged_filename")
    if not name:
        return None
    p = job_dir / str(name)
    return p if p.is_file() else None
