# -*- coding: utf-8 -*-
"""读取环境与路径配置（密钥仅从环境变量 / .env 加载，禁止写死在代码里）。"""
# 导入 pathlib，用于表示本项目根目录与仓库根目录
from pathlib import Path
# 导入 os，用于读取环境变量
import os
# 导入 shutil，用于清空已存在的输出目录
import shutil
# 导入 datetime，用于合并稿文件名中的时间戳
from datetime import datetime


def _normalize_ollama_api_key(raw: str) -> str:
    """
    去掉首尾空白，并兼容用户在变量里写了「Bearer xxx」导致的双重 Bearer。

    @param raw - 原始环境变量或 .env 中的字符串
    @returns 仅含密钥本体的字符串
    """
    s = raw.strip()  # 去掉两侧空白与常见误敲空格
    low = s.lower()  # 转小写便于前缀判断（不改动密钥本体大小写混合情形）
    bearer = "bearer "  # HTTP Authorization 常用前缀长度占位
    if low.startswith(bearer):  # 若用户把整段 Bearer Token 写进了变量值
        s = s[len(bearer) :].strip()  # 去掉前缀并再次裁剪，避免请求头变成 Bearer Bearer …
    return s  # 返回规范化后的密钥串


def uses_ollama_cloud(base_url: str) -> bool:
    """
    判断 base_url 是否指向 ollama.com 云端网关（此类请求必须携带 API Key）。

    @param base_url - 与 ChatOllama 一致的 Host 字符串
    @returns True 表示需要云端鉴权
    """
    return "ollama.com" in base_url.strip().lower()  # 域名匹配即可覆盖官网与可能的子域


# 缺密钥时的中文说明（CLI 与示例脚本共用，避免各处复制粘贴不一致）
CLOUD_KEY_REQUIRED_MSG = (
    "访问 Ollama 云端 API 需要有效的 OLLAMA_API_KEY，但当前环境未读到非空密钥。\n"
    "请任选其一：\n"
    "  1) 复制仓库根目录 ``.env.example`` 为 ``.env``（或在 ``aippt/.env``），填写 OLLAMA_API_KEY=你的密钥；\n"
    "  2) PowerShell 临时设置：$env:OLLAMA_API_KEY=\"你的密钥\"\n"
    "若已配置仍返回 401：请到 https://ollama.com/settings/keys 确认密钥未被撤销；"
    "变量值只需密钥本体，不要前缀 Bearer；.env 请保存为 UTF-8。\n"
)


# 尝试加载 .env：优先仓库根（便于与 Flask 等共用），其次包目录（开发时常放 aippt/.env）（可选依赖 python-dotenv）
try:
    # 从 dotenv 模块导入 load_dotenv 函数
    from dotenv import load_dotenv

    _pkg = Path(__file__).resolve().parent
    _root = _pkg.parent
    # utf-8-sig 可去掉 Windows 记事本保存带 BOM 的文件导致的「首变量读不到」问题
    load_dotenv(_root / ".env", encoding="utf-8-sig")
    load_dotenv(_pkg / ".env", encoding="utf-8-sig")
except ImportError:
    # 若未安装 python-dotenv，则跳过静默加载
    pass

# ``aippt`` Python 包目录绝对路径
PACKAGE_DIR = Path(__file__).resolve().parent
# 仓库根目录（含 ``output_run``、``samples``、``web`` 等）
REPO_ROOT = PACKAGE_DIR.parent

# 示例输入与默认生成物目录（均在仓库根下，避免与包代码混在一起）
SAMPLES_DIR = REPO_ROOT / "samples"
DEFAULT_SAMPLE_INPUT = SAMPLES_DIR / "sample_input.txt"

# 默认输出目录（流水线生成的 HTML/PPTX 子文件夹）
DEFAULT_WORKDIR = REPO_ROOT / "output_run"

# 未指定 ``--max-slides`` 时，大纲由模型自定页数后的脚本侧硬上限（防止异常过长）
OUTLINE_AUTO_PAGES_HARD_CAP = 24


def prepare_clean_output_dir(path: Path) -> None:
    """
    创建输出目录：若路径已存在则先删除该目录及其全部内容，再新建空目录。

    @param path - 本次运行专属输出目录（如 ``output_run/文档名`` 或 ``--work-dir``）
    @returns None
    """
    target = path.expanduser().resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)


# Windows 保留设备名（仅 stem 完全命中时规避，避免无法创建目录）
_WIN_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def safe_output_run_subdir_name(stem: str) -> str:
    """
    将输入文档主文件名（不含后缀）净化为可在 ``output_run`` 下使用的子目录名。

    @param stem - ``Path.stem``，可能含中文
    @returns 可用于创建目录的片段；非法或空时回退为 ``document``
    """
    invalid = '\\/*?:"<>|'
    name = (stem or "").strip() or "document"
    for ch in invalid:
        name = name.replace(ch, "_")
    name = name.strip(" .") or "document"
    if name.upper() in _WIN_RESERVED_STEMS:
        name = f"{name}_演示稿"
    return name


def merged_deck_pptx_filename(document_stem: str) -> str:
    """
    合并演示稿文件名：导入文档主文件名（净化）+ 本地时间戳 ``YYYYMMDD_HHMMSS``。

    @param document_stem - 输入文件 ``Path.stem``（不含后缀）
    @returns 含 ``.pptx`` 后缀的文件名
    """
    base = safe_output_run_subdir_name(document_stem)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{stamp}.pptx"


# 统一采样温度：优先 LLM_TEMPERATURE，否则沿用 OLLAMA_TEMPERATURE，兼容旧文档
_temp_raw = os.environ.get("LLM_TEMPERATURE")
if _temp_raw is None:
    _temp_raw = os.environ.get("OLLAMA_TEMPERATURE", "0.3")
LLM_TEMPERATURE = float(_temp_raw)
# 与 LLM_TEMPERATURE 同步，便于外部仍按 README 只配置 OLLAMA_TEMPERATURE
OLLAMA_TEMPERATURE = LLM_TEMPERATURE

# Ollama 云端接口地址（可用环境变量覆盖）
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com").strip()
# Ollama API Key（永远不要写入源码或 Git）；规范化后可写回环境供 ollama 官方 Client 自动读取
OLLAMA_API_KEY = _normalize_ollama_api_key(os.environ.get("OLLAMA_API_KEY", ""))
if OLLAMA_API_KEY:
    os.environ["OLLAMA_API_KEY"] = OLLAMA_API_KEY  # 与 ollama 库内部 getenv 行为对齐，避免一侧有头一侧无头
# 云端模型名（须与 ollama.com 账号可用模型一致，可用环境变量覆盖）
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b").strip()

# DeepSeek OpenAPI（与 ChatDeepSeek 默认一致，见 https://api-docs.deepseek.com/）
DEEPSEEK_API_KEY = _normalize_ollama_api_key(os.environ.get("DEEPSEEK_API_KEY", ""))
if DEEPSEEK_API_KEY:
    os.environ["DEEPSEEK_API_KEY"] = DEEPSEEK_API_KEY  # 便于 ChatDeepSeek 从环境兜底读取
DEEPSEEK_API_BASE = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1").strip()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip()

# DeepSeek 缺少密钥时的说明文案
DEEPSEEK_KEY_REQUIRED_MSG = (
    "当前 LLM_PROVIDER=deepseek，但未读到有效的 DEEPSEEK_API_KEY。\n"
    "请在仓库根目录 ``.env``（或 ``aippt/.env``）中填写 DEEPSEEK_API_KEY，或于 PowerShell 设置 "
    "$env:DEEPSEEK_API_KEY=\"你的密钥\"。\n"
    "密钥申请：https://platform.deepseek.com/api_keys\n"
)

# 未知 LLM 提供方时的模板（使用 format(p=...)）
UNKNOWN_LLM_PROVIDER_MSG = "未知 LLM_PROVIDER={p!r}，请设为 ollama 或 deepseek。\n"


def get_llm_provider() -> str:
    """
    读取当前选用的对话模型提供方（每次调用读环境变量，便于 CLI 在解析参数后覆盖）。

    @returns ``ollama`` 或 ``deepseek``（默认 ollama）
    """
    raw = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()  # 取出原始字符串并规范化
    return raw if raw else "ollama"  # 若用户误设为空白则回退默认


def resolve_llm_provider(explicit: str | None) -> str:
    """
    解析本次调用应使用的 provider（任务级覆盖优先于环境变量）。

    @param explicit - ``ollama`` / ``deepseek`` / None 或空串
    @returns 规范化后的 provider 标识
    """
    if explicit:
        p = explicit.strip().lower()
        if p in ("ollama", "deepseek"):
            return p
    return get_llm_provider()


def provider_auth_error_message(provider: str | None = None) -> str | None:
    """
    检查指定或当前 LLM_PROVIDER 下必填配置是否齐全。

    @param provider - 可选任务级 provider；None 时读环境变量
    @returns 若有缺失则返回 stderr 中文说明；否则 ``None``
    """
    prov = resolve_llm_provider(provider) if provider else get_llm_provider()
    if prov == "ollama":  # Ollama 分支
        if uses_ollama_cloud(OLLAMA_BASE_URL) and not OLLAMA_API_KEY:  # 云端且无密钥
            return CLOUD_KEY_REQUIRED_MSG  # 沿用原有 Ollama 指引
        return None  # 本地或已配置密钥
    if prov == "deepseek":  # DeepSeek OpenAPI 分支
        if not DEEPSEEK_API_KEY:  # 未配置密钥
            return DEEPSEEK_KEY_REQUIRED_MSG  # 返回 DeepSeek 专用提示
        return None  # 已就绪
    return UNKNOWN_LLM_PROVIDER_MSG.format(p=prov)  # 其它取值一律视为配置错误


def reload_llm_settings() -> None:
    """
    从环境变量刷新本模块中的 LLM 常量（写入 .env 后调用）。

    @returns None
    """
    global LLM_TEMPERATURE, OLLAMA_TEMPERATURE  # noqa: PLW0603
    global OLLAMA_BASE_URL, OLLAMA_API_KEY, OLLAMA_MODEL  # noqa: PLW0603
    global DEEPSEEK_API_KEY, DEEPSEEK_API_BASE, DEEPSEEK_MODEL  # noqa: PLW0603

    _temp_raw = os.environ.get("LLM_TEMPERATURE")
    if _temp_raw is None:
        _temp_raw = os.environ.get("OLLAMA_TEMPERATURE", "0.3")
    LLM_TEMPERATURE = float(_temp_raw or "0.3")
    OLLAMA_TEMPERATURE = LLM_TEMPERATURE

    OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com").strip()
    OLLAMA_API_KEY = _normalize_ollama_api_key(os.environ.get("OLLAMA_API_KEY", ""))
    if OLLAMA_API_KEY:
        os.environ["OLLAMA_API_KEY"] = OLLAMA_API_KEY
    else:
        os.environ.pop("OLLAMA_API_KEY", None)
    OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:120b").strip()

    DEEPSEEK_API_KEY = _normalize_ollama_api_key(os.environ.get("DEEPSEEK_API_KEY", ""))
    if DEEPSEEK_API_KEY:
        os.environ["DEEPSEEK_API_KEY"] = DEEPSEEK_API_KEY
    else:
        os.environ.pop("DEEPSEEK_API_KEY", None)
    DEEPSEEK_API_BASE = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1").strip()
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip()
