# -*- coding: utf-8 -*-
"""Web 任务目录与 progress/meta 文件读写（无 Flask / LangChain）。"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from aippt.config import REPO_ROOT

_ALLOWED_UPLOAD_EXT = frozenset({".txt", ".md", ".docx"})
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

MAX_WIZARD_RESTORE_DOCUMENT_CHARS = 2_000_000


def web_jobs_root() -> Path:
    """
    Web 任务根目录：仓库 ``output_run/web_jobs``。

    @returns 绝对路径
    """
    return (REPO_ROOT / "output_run" / "web_jobs").resolve()


def resolve_job_dir(job_id: str) -> Path:
    """
    解析任务目录并防止路径穿越。

    @param job_id - UUID 字符串
    @returns 任务目录绝对路径
    @raises ValueError - ID 非法或路径逃逸
    """
    if not _UUID_RE.match(job_id.strip()):
        raise ValueError("invalid job id")
    root = web_jobs_root()
    target = (root / job_id).resolve()
    try:
        target.relative_to(root)
    except ValueError as err:
        raise ValueError("invalid job path") from err
    return target


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """
    将字典原子写入 JSON 文件。

    @param path - 目标路径
    @param data - 可 JSON 序列化的字典
    @returns None
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_progress(job_dir: Path) -> dict[str, Any]:
    """
    读取进度文件；不存在则返回占位对象。

    @param job_dir - 任务目录
    @returns 进度字典
    """
    p = job_dir / "progress.json"
    if not p.is_file():
        return {"phase": "idle", "message": ""}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"phase": "error", "message": "progress.json 损坏"}


def read_meta(job_dir: Path) -> dict[str, Any]:
    """
    读取 meta.json。

    @param job_dir - 任务目录
    @returns 元数据字典；不存在时为空 dict
    """
    m = job_dir / "meta.json"
    if not m.is_file():
        return {}
    return json.loads(m.read_text(encoding="utf-8"))


def write_meta(job_dir: Path, meta: dict[str, Any]) -> None:
    """
    写入 meta.json。

    @param job_dir - 任务目录
    @param meta - 元数据
    @returns None
    """
    atomic_write_json(job_dir / "meta.json", meta)


def create_job() -> str:
    """
    新建任务 ID 并创建空目录。

    @returns UUID 字符串
    """
    job_id = str(uuid.uuid4())
    root = web_jobs_root()
    root.mkdir(parents=True, exist_ok=True)
    job_dir = root / job_id
    job_dir.mkdir(parents=False, exist_ok=False)
    atomic_write_json(
        job_dir / "progress.json",
        {"phase": "uploaded", "message": "已上传，等待生成大纲"},
    )
    return job_id


def allowed_upload_extensions() -> frozenset[str]:
    """@returns 允许上传的扩展名集合。"""
    return _ALLOWED_UPLOAD_EXT
