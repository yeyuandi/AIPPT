# -*- coding: utf-8 -*-
"""分步向导 HTTP API 与首页（对齐 CLI 流水线阶段）。"""
from __future__ import annotations

import json

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
)
from pydantic import ValidationError

from aippt.services import deck_jobs as wf
from aippt.chains import DECK_TEMPLATE_HTML_FILENAME
from aippt.config import REPO_ROOT, provider_auth_error_message, reload_llm_settings
from aippt.domain import DeckOutline
from aippt.settings import LLM_ENV_KEYS, read_llm_settings, write_llm_settings

bp = Blueprint("wizard", __name__)


def _json_err(message: str, code: int = 400):
    """统一 JSON 错误响应。"""
    return jsonify(error=message), code


@bp.route("/")
def index():
    """向导主页。"""
    return render_template("wizard.html")


@bp.get("/api/settings/llm")
def api_get_llm_settings():
    """读取 ``.env`` 中的 LLM 配置（供页面右上角「模型配置」）。"""
    try:
        settings = read_llm_settings()
    except OSError as err:
        current_app.logger.exception("读取 LLM 配置失败")
        return _json_err(f"无法读取 .env：{err}", 500)
    auth_err = provider_auth_error_message()
    return jsonify(
        settings=settings,
        env_path=str(REPO_ROOT / ".env"),
        auth_ok=auth_err is None,
        auth_message=auth_err,
    )


@bp.put("/api/settings/llm")
def api_put_llm_settings():
    """写入 ``.env`` 并刷新进程内 LLM 配置。"""
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _json_err("请求体须为 JSON 对象")

    updates: dict[str, str] = {}
    for key in LLM_ENV_KEYS:
        if key not in payload:
            continue
        val = payload[key]
        if val is None:
            updates[key] = ""
        else:
            updates[key] = str(val).strip()

    provider = updates.get("LLM_PROVIDER") or read_llm_settings().get("LLM_PROVIDER", "")
    if provider and provider not in ("ollama", "deepseek"):
        return _json_err("LLM_PROVIDER 须为 ollama 或 deepseek")

    if "LLM_TEMPERATURE" in updates and updates["LLM_TEMPERATURE"]:
        try:
            t = float(updates["LLM_TEMPERATURE"])
        except ValueError:
            return _json_err("LLM_TEMPERATURE 须为数字")
        if not 0 <= t <= 2:
            return _json_err("LLM_TEMPERATURE 建议在 0～2 之间")
        updates["OLLAMA_TEMPERATURE"] = updates["LLM_TEMPERATURE"]

    try:
        path = write_llm_settings(updates)
        reload_llm_settings()
    except OSError as err:
        current_app.logger.exception("写入 LLM 配置失败")
        return _json_err(f"无法写入 .env：{err}", 500)

    auth_err = provider_auth_error_message()
    return jsonify(
        ok=True,
        env_path=str(path),
        settings=read_llm_settings(),
        auth_ok=auth_err is None,
        auth_message=auth_err,
    )


@bp.post("/api/jobs")
def api_create_job_upload():
    """
    创建任务并上传文档（步骤 A）。

    form-data: file（可选）、document_text（可选）、llm_provider；须至少提供文件或正文其一。
    """
    f = request.files.get("file")
    has_file = bool(f and getattr(f, "filename", None))
    document_text = request.form.get("document_text")
    llm_provider = (request.form.get("llm_provider") or "").strip().lower() or None

    try:
        job_id = wf.create_job()
        preview = wf.save_document_source(
            job_id,
            f if has_file else None,
            document_text,
            llm_provider=llm_provider if llm_provider in ("ollama", "deepseek") else None,
        )
    except ValueError as err:
        return _json_err(str(err))
    except FileExistsError:
        return _json_err("任务目录冲突", 500)

    return jsonify(job_id=job_id, **preview)


@bp.get("/api/jobs/history")
def api_jobs_history():
    """列出本机 ``output_run/web_jobs`` 下可载入的历史任务（含 ``document.txt``）。"""
    try:
        jobs = wf.list_job_summaries()
    except OSError as err:
        current_app.logger.exception("列出历史任务失败")
        return _json_err(f"无法列出任务：{err}", 500)
    return jsonify(jobs=jobs)


@bp.get("/api/jobs/<job_id>/wizard-restore")
def api_wizard_restore(job_id: str):
    """返回恢复向导各步表单与预览所需的数据（含正文全文）。"""
    try:
        bundle = wf.wizard_restore_bundle(job_id)
    except ValueError as err:
        msg = str(err)
        if "invalid job id" in msg.lower():
            return _json_err("无效任务 ID", 404)
        return _json_err(msg, 400)
    except FileNotFoundError as err:
        return _json_err(str(err), 404)
    except Exception as err:
        current_app.logger.exception("wizard-restore job_id=%s", job_id)
        return _json_err(f"载入失败：{err}", 500)
    return jsonify(bundle)


def _coerce_optional_int(name: str, raw: object) -> int | None:
    """
    将 JSON 字段转为可选正整数（空值跳过）。

    @param name - 字段名（用于错误文案）
    @param raw - 原始值
    @returns 整数或 None
    @raises ValueError - 无法解析或非法
    """
    if raw is None or raw == "":
        return None
    try:
        i = int(raw)
    except (TypeError, ValueError) as err:
        raise ValueError(f"{name} 须为整数") from err
    if i < 1:
        raise ValueError(f"{name} 须 ≥ 1")
    return i


@bp.post("/api/jobs/<job_id>/outline")
def api_outline(job_id: str):
    """步骤 B：生成大纲。"""
    payload = request.get_json(silent=True) or {}
    max_slides = payload.get("max_slides")
    target_slides = payload.get("target_slides")
    try:
        max_slides_i = _coerce_optional_int("max_slides", max_slides)
        target_slides_i = _coerce_optional_int("target_slides", target_slides)
    except ValueError as err:
        return _json_err(str(err), 400)

    try:
        result = wf.run_outline_step(job_id, max_slides_i, target_slides_i)
    except ValueError as err:
        msg = str(err)
        if "invalid job" in msg:
            return _json_err("无效任务 ID", 404)
        return _json_err(msg, 400)
    except RuntimeError as err:
        return _json_err(str(err), 400)
    except FileNotFoundError as err:
        return _json_err(str(err), 404)
    except Exception as err:
        current_app.logger.exception("大纲生成失败 job_id=%s", job_id)
        return _json_err(f"大纲生成失败：{err}", 500)

    return jsonify(result)


@bp.post("/api/jobs/<job_id>/deck-template")
def api_deck_template(job_id: str):
    """步骤 C：生成 deck 模板 HTML。"""
    payload = request.get_json(silent=True) or {}
    html_style = str(payload.get("html_style") or "")

    try:
        result = wf.run_deck_template_step(job_id, html_style)
    except ValueError as err:
        msg = str(err)
        if "invalid job" in msg:
            return _json_err("无效任务 ID", 404)
        return _json_err(msg, 400)
    except RuntimeError as err:
        return _json_err(str(err), 400)
    except FileNotFoundError as err:
        return _json_err(str(err), 404)
    except Exception as err:
        current_app.logger.exception("deck 模板生成失败 job_id=%s", job_id)
        return _json_err(f"模板生成失败：{err}", 500)

    return jsonify(result)


@bp.post("/api/jobs/<job_id>/slides-html/start")
def api_slides_html_start(job_id: str):
    """步骤 D：异步启动逐页 HTML 生成。"""
    try:
        wf.start_slide_html_generation(job_id, current_app._get_current_object())
    except ValueError as err:
        msg = str(err)
        if "invalid job" in msg:
            return _json_err("无效任务 ID", 404)
        return _json_err(msg, 400)
    except RuntimeError as err:
        return _json_err(str(err), 409)
    except FileNotFoundError as err:
        return _json_err(str(err), 400)

    return jsonify(accepted=True)


@bp.post("/api/jobs/<job_id>/export-pptx/start")
def api_export_pptx_start(job_id: str):
    """步骤 E：异步导出 pptx 并合并；JSON 可选 raster_dpr（≥1）、save_slide_png（布尔）。"""
    payload = request.get_json(silent=True) or {}
    raster_raw = payload.get("raster_dpr")
    raster_dpr_f: float | None = None
    if raster_raw is not None and raster_raw != "":
        try:
            raster_dpr_f = float(raster_raw)
        except (TypeError, ValueError):
            return _json_err("raster_dpr 必须为数字")
        if raster_dpr_f < 1:
            return _json_err("raster_dpr 须 ≥ 1")

    save_slide_png: bool | None = None
    if "save_slide_png" in payload:
        raw_png = payload.get("save_slide_png")
        if not isinstance(raw_png, bool):
            return _json_err("save_slide_png 须为布尔值", 400)
        save_slide_png = raw_png

    try:
        wf.start_export_pptx(
            job_id,
            current_app._get_current_object(),
            raster_dpr=raster_dpr_f,
            save_slide_png=save_slide_png,
        )
    except ValueError as err:
        msg = str(err)
        if "invalid job" in msg:
            return _json_err("无效任务 ID", 404)
        return _json_err(msg, 400)
    except RuntimeError as err:
        return _json_err(str(err), 409)
    except FileNotFoundError as err:
        return _json_err(str(err), 400)

    return jsonify(accepted=True)


@bp.get("/api/jobs/<job_id>/progress")
def api_progress(job_id: str):
    """轮询任务进度。"""
    try:
        job_dir = wf.resolve_job_dir(job_id)
    except ValueError:
        return _json_err("无效任务 ID", 404)

    return jsonify(wf.read_progress(job_dir))


@bp.get("/api/jobs/<job_id>/outline-json")
def api_outline_json_file(job_id: str):
    """
    返回任务目录下的 ``deck_outline.json`` 原始结构（供前端「选择页面」等加载）。

    @returns JSON 对象，含 ``slides`` 数组
    """
    try:
        job_dir = wf.resolve_job_dir(job_id)
    except ValueError:
        return _json_err("无效任务 ID", 404)

    path = job_dir / "deck_outline.json"
    if not path.is_file():
        return _json_err("暂无 deck_outline.json", 404)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _json_err("deck_outline.json 无法解析", 500)

    if not isinstance(data, dict):
        return _json_err("deck_outline.json 根节点须为对象", 500)

    return jsonify(data)


@bp.put("/api/jobs/<job_id>/outline-json")
def api_put_outline_json(job_id: str):
    """将编辑后的结构化大纲写回 ``deck_outline.json`` / ``deck_outline.txt``（请求体与 GET 返回结构一致）。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _json_err("请求体须为 JSON 对象（含 slides 数组）", 400)

    try:
        deck, outline_plain = wf.save_deck_outline_files(job_id, payload)
    except ValidationError as err:
        return _json_err(f"大纲格式不符合 Schema：{err}", 400)
    except ValueError as err:
        msg = str(err)
        if "invalid job" in msg:
            return _json_err("无效任务 ID", 404)
        return _json_err(msg, 400)
    except Exception as err:
        current_app.logger.exception("保存大纲失败 job_id=%s", job_id)
        return _json_err(f"保存失败：{err}", 500)

    return jsonify(
        ok=True,
        slide_count=len(deck.slides),
        outline_plain=outline_plain,
        outline_json=deck.model_dump(),
    )


@bp.get("/api/jobs/<job_id>/slide-meta")
def api_slide_meta(job_id: str):
    """大纲页标题列表（用于预览切换）。"""
    try:
        job_dir = wf.resolve_job_dir(job_id)
    except ValueError:
        return _json_err("无效任务 ID", 404)

    outline_path = job_dir / "deck_outline.json"
    if not outline_path.is_file():
        return _json_err("暂无大纲", 404)

    outline = DeckOutline.model_validate_json(outline_path.read_text(encoding="utf-8"))
    titles = [{"index": i, "title": s.title} for i, s in enumerate(outline.slides)]
    return jsonify(slides=titles, count=len(titles))


@bp.get("/api/jobs/<job_id>/deck-template-ready")
def api_deck_template_ready(job_id: str):
    """探测 deck_template.html 是否已生成。

    模板未就绪时仍返回 200 + ``{"ready": false}``，避免对 HTML 预览 URL 使用 HEAD 时在访问日志中出现 404。
    """
    try:
        job_dir = wf.resolve_job_dir(job_id)
    except ValueError:
        return _json_err("无效任务 ID", 404)

    ready = (job_dir / DECK_TEMPLATE_HTML_FILENAME).is_file()
    return jsonify(ready=ready)


@bp.get("/api/jobs/<job_id>/html/deck-template")
def api_html_deck_template(job_id: str):
    """预览 deck_template.html。"""
    try:
        job_dir = wf.resolve_job_dir(job_id)
    except ValueError:
        abort(404)

    path = job_dir / DECK_TEMPLATE_HTML_FILENAME
    if not path.is_file():
        abort(404)

    return Response(path.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")


@bp.get("/api/jobs/<job_id>/html/slide/<int:idx>")
def api_html_slide(job_id: str, idx: int):
    """预览单页 slide_NNN.html。"""
    try:
        job_dir = wf.resolve_job_dir(job_id)
    except ValueError:
        abort(404)

    path = job_dir / f"slide_{idx:03d}.html"
    if not path.is_file():
        abort(404)

    return Response(path.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")


@bp.put("/api/jobs/<job_id>/html/slide/<int:idx>")
def api_put_html_slide(job_id: str, idx: int):
    """将编辑后的 HTML 写回 ``slide_NNN.html``（JSON 字段 ``html``）。"""
    payload = request.get_json(silent=True) or {}
    html = payload.get("html")
    if not isinstance(html, str):
        return _json_err("请求体须为 JSON，且包含字符串字段 html", 400)

    try:
        filename = wf.save_slide_html(job_id, idx, html)
    except ValueError as err:
        msg = str(err)
        if "invalid job" in msg:
            return _json_err("无效任务 ID", 404)
        return _json_err(msg, 400)
    except FileNotFoundError as err:
        return _json_err(str(err), 404)
    except Exception as err:
        current_app.logger.exception("保存单页 HTML 失败 job_id=%s idx=%s", job_id, idx)
        return _json_err(f"保存失败：{err}", 500)

    return jsonify(ok=True, filename=filename)


@bp.get("/api/jobs/<job_id>/download/merged")
def api_download_merged(job_id: str):
    """下载合并后的 pptx（步骤 F）。"""
    try:
        path = wf.merged_pptx_path(job_id)
    except ValueError:
        abort(404)

    if path is None:
        abort(404)

    return send_file(
        path,
        as_attachment=True,
        download_name=path.name,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
