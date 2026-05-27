# -*- coding: utf-8 -*-
"""读写仓库根目录 ``.env`` 中的 LLM 相关配置。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from aippt.config import REPO_ROOT

# 允许通过 Web/API 读写的键（顺序用于新建 .env 时的默认段落）
LLM_ENV_KEYS: tuple[str, ...] = (
    "LLM_PROVIDER",
    "LLM_TEMPERATURE",
    "OLLAMA_API_KEY",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_BASE",
    "DEEPSEEK_MODEL",
)

_ENV_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def env_file_path() -> Path:
    """
    @returns 优先使用的 .env 路径（仓库根）
    """
    return REPO_ROOT / ".env"


def _load_dotenv_override() -> None:
    """将 .env 刷入 ``os.environ``（覆盖已有值）。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    path = env_file_path()
    if path.is_file():
        load_dotenv(path, encoding="utf-8-sig", override=True)


def read_llm_settings() -> dict[str, str]:
    """
    读取当前 LLM 配置（先刷新 .env 再读环境变量）。

    @returns 键值字典，缺失键为空字符串
    """
    _load_dotenv_override()
    out: dict[str, str] = {}
    for key in LLM_ENV_KEYS:
        if key == "LLM_TEMPERATURE":
            raw = os.environ.get("LLM_TEMPERATURE") or os.environ.get("OLLAMA_TEMPERATURE", "")
        else:
            raw = os.environ.get(key, "")
        out[key] = (raw or "").strip()
    return out


def _format_env_value(value: str) -> str:
    """
    格式化为 ``KEY=value`` 行中的 value 部分。

    @param value - 原始值
    @returns 无需引号时可原样；含空白或 # 时用双引号包裹
    """
    if value == "":
        return ""
    if re.search(r'[\s#"\']', value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def write_llm_settings(updates: dict[str, Any]) -> Path:
    """
    合并写入 ``.env``（保留未知行与注释）。

    @param updates - 仅接受 ``LLM_ENV_KEYS`` 中的键
    @returns 写入的 .env 路径
    """
    path = env_file_path()
    allowed = {k: str(v).strip() for k, v in updates.items() if k in LLM_ENV_KEYS}

    existing_lines: list[str] = []
    if path.is_file():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    seen: set[str] = set()
    new_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        m = _ENV_LINE_RE.match(stripped)
        if not m:
            new_lines.append(line)
            continue
        key = m.group(1)
        if key in allowed:
            new_lines.append(f"{key}={_format_env_value(allowed[key])}")
            seen.add(key)
        else:
            new_lines.append(line)

    missing = [k for k in LLM_ENV_KEYS if k in allowed and k not in seen]
    if missing:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# --- LLM（由 Web 向导写入）---")
        for key in LLM_ENV_KEYS:
            if key in missing:
                new_lines.append(f"{key}={_format_env_value(allowed[key])}")

    text = "\n".join(new_lines).rstrip() + "\n"
    path.write_text(text, encoding="utf-8")
    _load_dotenv_override()
    from aippt.config import reload_llm_settings

    reload_llm_settings()
    return path
