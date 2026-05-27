# `aippt` 包 — 技术说明

本文件是 **`aippt` Python 包**的开发者手册（流水线细节、CLI 速查、模块职责、排错）。

- 仓库总览、安装与快速上手 → **[../README.md](../README.md)**
- 补充文档 → **[../docs/](../docs/)**（[HTML→PPTX](../docs/html_to_ppt.md)、[FAQ](../docs/faq.md)）
- Web 向导（Flask）→ **`../apps/web/`**，启动：`flask --app apps.web.app:create_app`

---

## 文档目录

1. [流水线概览](#流水线概览)
2. [架构与分层](#架构与分层)
3. [包内目录](#包内目录)
4. [导出模型](#导出模型)
5. [命令行入口](#命令行入口) · [命令速查](#命令速查)
6. [Web 编排（`services`）](#web-编排services)
7. [环境变量](#环境变量)
8. [大纲与页型](#大纲与页型)
9. [编程调用](#编程调用)
10. [常见问题](#常见问题)（完整版见 **[../docs/faq.md](../docs/faq.md)**）

**维护约定**：变更 `aippt/` 内 CLI、环境变量、导出行为或 `services` 编排时，请同步更新本文件、仓库根 **[README.md](../README.md)**，以及 **[../docs/](../docs/)** 中相关专题。

---

## 流水线概览

从 **Word / 文本 / Markdown** 到合并 **PPTX** 的固定顺序：

| 步骤 | 模块 | 产出 |
|------|------|------|
| 1 | `aippt.io` | 文档正文 |
| 2 | `chains.build_outline_chain` | `deck_outline.json` |
| 3 | `chains.build_deck_html_template_chain` | `deck_template.html` |
| 4 | `chains.build_raster_*_slide_chain` | `slide_NNN.html`（封面 / 目录 / 正文） |
| 5 | `export.run_html_to_ppt` | `slide_NNN.pptx`（截取 **`.slide`**） |
| 6 | `export.merge_pptx_files` | `<主名>_YYYYMMDD_HHMMSS.pptx` |

**离线二次加工**（不调 LLM）：`python -m aippt.export.rerender_html_dir` 批量重截图，或 `--merge-only` 仅按大纲合并已有 pptx。

**实现要点**：

- 栅格内核：`export/html_to_ppt.py`（`HtmlToPptConverter`）
- 进程内/Agent 推荐：`export/html_to_ppt_tools.run_html_to_ppt` + `HtmlToPptCliOptions`
- 合并：`export/merge_pptx.py`（无独立 `python -m merge_pptx`）

---

## 架构与分层

```text
apps/web/          HTTP、模板、REST（仅调用下方 services）
       ↓
aippt/services/    编排：invoke_outline_chain、deck_jobs、job_store
       ↓
aippt/chains/      LCEL：prompt | llm | parser
       ↓
aippt/llm/         build_chat_llm(provider=…)
aippt/prompts/     提示词与布局 CSS
aippt/parsers/     JSON / HTML 围栏解析
aippt/domain/      DeckOutline（Pydantic）
       ↓
aippt/export/      Playwright 截图、pptx 合并
```

**依赖规则（请勿破坏）**：

| 允许 | 禁止 |
|------|------|
| `services` → `chains`、`domain`、`export`、`io` | `chains` → `flask` / `apps` |
| `chains` → `prompts`、`parsers`、`llm` | `prompts` → `llm` |
| `apps/web` → `aippt.services` | `aippt` 任意模块 → Flask |

任务级 LLM 后端通过 **`build_chat_llm(provider=meta["llm_provider"])`** 传入，**不要**在并发 Web 任务里临时改 `os.environ["LLM_PROVIDER"]`。

---

## 包内目录

```text
aippt/
├── __main__.py              # python -m aippt → cli.pipeline.main
├── config.py                # 路径、环境变量、resolve_llm_provider
├── cli/
│   ├── pipeline.py          # 主流水线 CLI
│   └── example_invoke.py    # 带进度输出的示例
├── io/                      # load_document_text
├── settings/                # .env 中 LLM 键读写
├── domain/                  # DeckOutline、序列化
├── llm/                     # build_chat_llm
├── prompts/                 # ChatPromptTemplate 正文
├── parsers/                 # parse_outline_json、strip_fence
├── chains/                  # outline.py、deck_html.py、prompt_vars.py
├── services/
│   ├── outline.py           # invoke_outline_chain、cap_outline_pages
│   ├── deck_jobs.py         # Web 六步向导业务
│   └── job_store.py         # web_jobs、progress.json
├── export/                  # html_to_ppt、merge、rerender_html_dir
├── search/                  # DuckDuckGo 等 Tool（可选）
├── media/、tts/             # 音视频工具（可选，非主路径）
├── pipeline.py              # 兼容：转发 cli.pipeline
├── example_invoke.py        # 兼容：转发 cli.example_invoke
└── env_file.py              # 兼容：转发 settings
```

### 模块职责

| 路径 | 职责 |
|------|------|
| `cli/pipeline.py` | `python -m aippt` |
| `cli/example_invoke.py` | `python -m aippt.example_invoke` |
| `services/outline.py` | CLI / Web 共用的大纲生成 |
| `services/deck_jobs.py` | 上传、分步生成、`output_run/web_jobs/<id>/` |
| `services/job_store.py` | `meta.json`、`progress.json`、任务目录 |
| `chains/` | `build_outline_chain`、`build_raster_*_slide_chain` |
| `llm/factory.py` | Ollama / DeepSeek 构造 |
| `export/html_to_ppt.py` | 单页截图导出 |
| `export/html_to_ppt_tools.py` | `run_html_to_ppt`、LangChain Tool |
| `export/rerender_html_dir.py` | 目录批量重跑 / 仅合并 |
| `export/merge_pptx.py` | `merge_pptx_files` |

---

## 导出模型

- **截图范围**：仅 **`.slide`** 边界框内像素；`overflow:hidden`，溢出会被裁切。排版约束见 `prompts/`（`minmax(0,1fr)`、`min-height:0` 等）。
- **尺寸**：默认幻灯片宽约 **7.5×16/9 英寸**、高 **7.5 英寸**；视口默认 **1200×675**（16:9）。流水线默认 `fit_slide_viewport=True`。
- **产物**：每页为**栅格图**，PPT 内文字不可编辑；合并时复制形状并重映射图片 `r:embed`（复杂 OLE/图表未完整支持）。

---

## 命令行入口

### 前置条件

1. 在**仓库根目录**执行（保证能 `import aippt`）。
2. 已 `pip install -r requirements.txt` 且 `python -m playwright install chromium`。
3. 已配置 `.env`（见 [环境变量](#环境变量)）。

### 命令速查

| 场景 | 命令 |
|------|------|
| 全文生成 | `python -m aippt --input … --work-dir …` |
| 示例脚本（进度输出） | `python -m aippt.example_invoke --input …` |
| 单页 HTML → pptx | `python -m aippt.export.html_to_ppt slide_000.html --fit-slide-viewport --raster-dpr 10` |
| 目录批量重截图 + 合并 | `python -m aippt.export.rerender_html_dir path\to\run --merge --raster-dpr 10` |
| 仅合并已有 pptx | `python -m aippt.export.rerender_html_dir path\to\run --merge-only` |
| 大纲硬上限 + 软目标 | `python -m aippt … --max-slides 25 --target-slides 22` |
| 切换 DeepSeek | `python -m aippt --llm-provider deepseek …` |

---

### 入口 A：`python -m aippt`

实现：`cli/pipeline.py`。

| 参数 | 说明 |
|------|------|
| `--input` | `.txt` / `.md` / `.docx`，默认 `samples/sample_input.txt` |
| `--work-dir` | 输出根目录；等于默认 `output_run` 时落到 `output_run/<文档主文件名>/`；**已存在则整目录清空** |
| `--max-slides` | 大纲硬上限；省略时模型自拟（脚本硬上限 **24**） |
| `--target-slides` | 软目标（写入提示词）；须 ≤ `--max-slides`（若指定） |
| `--raster-dpr` | Playwright `device_scale_factor`，默认 `10` |
| `--html-style` | 风格描述（写入 HTML 提示词） |
| `--skip-merge` | 只生成各页 `slide_NNN.pptx` |
| `--llm-provider` | `ollama` \| `deepseek` |
| `--save-slide-png` | 额外写入 `slide_NNN.png` |

**产出**：`deck_outline.json` / `.txt`、`deck_template.html`、`slide_NNN.html` / `.pptx`、合并稿 `<主名>_YYYYMMDD_HHMMSS.pptx`。

```bash
python -m aippt --input samples/sample_input.txt --work-dir output_run
python -m aippt --input ./report.docx --work-dir output_run --max-slides 25 --target-slides 22
```

---

### 入口 B：`python -m aippt.example_invoke`

实现：`cli/example_invoke.py`。默认写入 `output_run/<输入主文件名>/`，终端带 `[示例]` 进度行。

参数与入口 A 类似，另支持 `--save-slide-png`。单页 HTML **不得**整段拷贝 `deck_template.html` 的 `<style>`。

**`--html-style` 示例**（节选）：

| 场景 | 示例 |
|------|------|
| 科技 / SaaS | `深色科技感，冷色渐变，极简未来风` |
| 金融 / 政务 | `稳重商务，深蓝或红白Classic，层级清晰` |
| 教育 | `明快友好，高可读大字，课堂演示感` |

---

### 入口 C：`python -m aippt.export.rerender_html_dir`

对已生成目录**批量 HTML→pptx**，或**仅合并**（不调 LLM）。

| 参数 | 说明 |
|------|------|
| `html_dir` | 目标目录 |
| `--merge` | 按处理顺序合并为一个 pptx |
| `--merge-only` | 不截图；按 `deck_outline.json` 的 `pptx_file` 顺序合并 |
| `--outline-file` | `--merge-only` 时大纲路径 |
| `--only` | 只处理列出的 HTML（顺序即合并顺序） |
| `--raster-dpr` | 默认 `10`（`--merge-only` 时不生效） |

---

### 入口 D：`python -m aippt.export.html_to_ppt`

单文件 HTML → 同目录 pptx（或 `-o` 指定路径）。参数详见 **[../docs/html_to_ppt.md](../docs/html_to_ppt.md)**。

---

## Web 编排（`services`）

Flask 应用在 **`../apps/web/`**，不放在本包内。

| 步骤 | `deck_jobs` / API 概要 |
|------|-------------------------|
| 上传 | `save_document_source` → `document.txt` |
| 大纲 | `run_outline_step` |
| 模板 | `run_deck_template_step` |
| 逐页 HTML | `start_slide_html_generation`（后台线程 + `progress.json`） |
| 导出 | `start_export_pptx` |
| 任务目录 | `output_run/web_jobs/<job_id>/` |

Web 读写 `.env` 使用 **`aippt.settings`**（`read_llm_settings` / `write_llm_settings`）。生产环境请设置 `FLASK_SECRET_KEY`。

---

## 环境变量

与仓库根 **[`.env.example`](../.env.example)** 对齐；读写实现见 **`settings/env_file.py`**。

| 变量 | 说明 |
|------|------|
| `LLM_PROVIDER` | `ollama`（默认）\| `deepseek` |
| `LLM_TEMPERATURE` | 采样温度，默认 `0.3` |
| `OLLAMA_API_KEY` | 使用 `ollama.com` 云端时必填 |
| `OLLAMA_BASE_URL` | 默认 `https://ollama.com` |
| `OLLAMA_MODEL` | 须与可用模型一致 |
| `DEEPSEEK_API_KEY` | `LLM_PROVIDER=deepseek` 时必填 |
| `DEEPSEEK_API_BASE` | 默认 `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 默认 `deepseek-chat` |
| `FLASK_SECRET_KEY` | Web 生产环境 |
| `FLASK_MAX_UPLOAD_MB` | 上传上限（MB），默认 `32` |

加载逻辑：`config.py` 在 import 时 `load_dotenv` 仓库根 `.env`（及可选 `aippt/.env`）。

---

## 大纲与页型

**输入**

- `.txt` / `.md`：UTF-8（`utf-8-sig` 去 BOM）
- `.docx`：`python-docx` 抽取段落与表格（单元格以 ` | ` 连接）

**页型**（与 `prompts/`、`chains/` 一致）

1. `slides[0]`：封面  
2. 总页数 ≥ 3：`slides[1]` 为目录，`bullets` 对应正文标题  
3. 正文：自 `slides[2]` 起（仅 1～2 页时不单独生成目录页）  
4. `deck_outline.json` 含 `html_file` / `pptx_file`（`assign_slide_output_filenames` 写入）

---

## 编程调用

### 推荐 import

```python
from aippt.llm import build_chat_llm
from aippt.domain import DeckOutline
from aippt.services.outline import invoke_outline_chain, cap_outline_pages
from aippt.services import deck_jobs
from aippt.io import load_document_text
from aippt.settings import read_llm_settings, write_llm_settings
from aippt.export.html_to_ppt_tools import run_html_to_ppt, HtmlToPptCliOptions
from aippt.export.merge_pptx import merge_pptx_files
```

### 单页导出示例

```python
from aippt.export.html_to_ppt_tools import convert_html_file_to_pptx

convert_html_file_to_pptx(
    input_html_path="output_run/demo/slide_000.html",
    output_pptx_path="output_run/demo/slide_000.pptx",
)
```

### LangChain

- LCEL：`ChatPromptTemplate` | `llm` | `RunnableLambda` / Pydantic 解析  
- Ollama：`langchain-ollama`；DeepSeek：`langchain-deepseek`  
- 版本约束见根目录 `requirements.txt`（`langchain-core>=1.3,<2`）

---

## 常见问题

包内速查：

| 现象 | 处理 |
|------|------|
| Playwright / Chromium 报错 | `python -m playwright install chromium` |
| Ollama 401 | 检查 `OLLAMA_API_KEY`；勿带 `Bearer` 前缀 |
| 底部文字被裁切 | 收紧内容；见 `prompts/` 布局约束 |
| 与浏览器预览不一致 | 少用 `vw`/`vh`；视口 1200×675 |
| HTML→PPTX 全参数 | [docs/html_to_ppt.md](../docs/html_to_ppt.md) |
| Web 任务卡住 | `web_jobs/<id>/progress.json` |

安装、LLM、导出、Web 部署等完整 FAQ → **[../docs/faq.md](../docs/faq.md)**。

---

## 依赖（本包）

在仓库根安装：

```bash
pip install -r requirements.txt
```

核心：`langchain-core`、`langchain`、`langchain-ollama`、`langchain-deepseek`、`playwright`、`python-pptx`、`python-docx`、`pydantic`、`python-dotenv`、`flask` 等（以 `requirements.txt` 为准）。
