# 常见问题（FAQ）

与安装、LLM 配置、排版导出、Web 向导相关的问题汇总。命令行参数详见 [aippt/README.md](../aippt/README.md)；HTML→PPTX 详见 [html_to_ppt.md](html_to_ppt.md)。

---

## 安装与依赖

### `ModuleNotFoundError: playwright` 或浏览器启动失败

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### `ImportError: langchain_deepseek`

使用 DeepSeek 时需安装：

```bash
pip install langchain-deepseek
```

（已列入根目录 `requirements.txt`。）

### 读取 `.docx` 失败

```bash
pip install python-docx
```

---

## LLM 与 `.env`

### Ollama 返回 401

1. 在 [ollama.com/settings/keys](https://ollama.com/settings/keys) 确认密钥有效。  
2. `.env` 中 `OLLAMA_API_KEY` **不要**写 `Bearer ` 前缀。  
3. 使用云端时 `OLLAMA_BASE_URL` 应指向 `https://ollama.com`（或你的网关）。  
4. Windows 记事本保存 `.env` 建议 **UTF-8**，避免 BOM 导致首变量读不到（项目已用 `utf-8-sig` 加载）。

### DeepSeek 无响应或鉴权失败

1. 设置 `LLM_PROVIDER=deepseek` 与有效的 `DEEPSEEK_API_KEY`。  
2. CLI：`python -m aippt --llm-provider deepseek …`  
3. Web 任务可在上传时选择 provider，写入 `meta.json`，**无需**改全局环境变量。

### 如何切换模型？

编辑 `.env` 中 `OLLAMA_MODEL` 或 `DEEPSEEK_MODEL`，或在 Web 向导「模型配置」中保存（写入 `.env`）。

---

## 大纲与页数

### 页数太多 / 太少

- **硬上限**：`--max-slides N`（CLI）或 Web 大纲步骤填写。  
- **软目标**：`--target-slides N`（写入提示词，模型尽量接近）。  
- 未指定 `max-slides` 时，脚本有硬上限 **24** 页（见 `aippt.config.OUTLINE_AUTO_PAGES_HARD_CAP`）。

### 没有目录页

目录页仅在 **总页数 ≥ 3** 时生成（`slides[1]`）。仅 1～2 页时不单独做目录。

---

## 导出与排版

### PPT 里文字不能编辑？

设计如此：导出为 **`.slide` 区域截图** 栅格图，不是原生文本框。若需可编辑文本，需另选矢量/HTML 转形状方案（本仓库主路径为 raster）。

### 与浏览器打开 HTML 效果不一致

1. 导出使用**固定视口**（默认 1200×675），不是浏览器窗口任意大小。  
2. 避免在 HTML 中依赖 `100vw`/`100vh` 做关键尺寸。  
3. 本地预览时可用与 `DEFAULT_PLAYWRIGHT_VIEWPORT_WIDTH_PX` 相同的宽度调试。

### 底部或右侧内容被裁切

1. `.slide` 使用 `overflow: hidden`，溢出部分不会出现在截图中。  
2. 减少要点或缩短概要；调整 `html-style` 让版式更松。  
3. 参考 `aippt/prompts/` 中 Grid `minmax(0,1fr)`、`min-height:0` 等约束。

### 幻灯片看起来缩小、四周有白边

1. 开启 **`fit_slide_viewport=True`**（流水线默认已开）。  
2. 幻灯片物理宽高比须与视口一致（默认精确 16:9）。  
3. 单文件 CLI 默认 `--raster-dpr 1` 时也可能显得发虚，可提高到 `10`。

### 只想重新导出 pptx、不调 LLM

```bash
python -m aippt.export.rerender_html_dir output_run/某次运行 --merge --raster-dpr 10
```

已有各页 pptx，仅合并：

```bash
python -m aippt.export.rerender_html_dir output_run/某次运行 --merge-only
```

---

## Web 向导

### 任务一直停在「生成中」

查看 `output_run/web_jobs/<job_id>/progress.json`：

| `phase` | 含义 |
|---------|------|
| `slides_running` | 正在逐页生成 HTML |
| `pptx_running` | 正在 Playwright 导出 |
| `error` | 失败，`message` 有原因 |

刷新页面或重新打开向导；若进程已崩溃，需重新执行对应步骤。

### 上传失败或文件过大

- 检查 `FLASK_MAX_UPLOAD_MB`（默认 32）。  
- 支持 `.txt` / `.md` / `.docx`。

### 生产部署注意

1. 设置 **`FLASK_SECRET_KEY`**。  
2. 不要用 `flask run --debug`。  
3. 使用 `gunicorn` / `waitress` 等 WSGI 服务器（自行配置）。  
4. 长任务仍在进程内线程执行，多 worker 时任务目录需共享存储或改为任务队列（未内置）。

---

## 开发与贡献

### 应改哪些文档？

| 变更类型 | 更新 |
|----------|------|
| 新 CLI / 环境变量 | 根 `README.md`、`aippt/README.md`、`.env.example` |
| 导出参数 | `docs/html_to_ppt.md`、本 FAQ |
| Web API | `aippt/README.md` Web 一节 |

### 历史「apograph 矢量导出」？

主流水线已移除矢量 apograph 路径；若仓库内仍有 `docs/prompt_generate_apograph_html.md` 仅供考古参考，**勿**与当前 raster 流水线混用。

---

## 仍无法解决？

1. 附带 `progress.json` 或终端完整报错。  
2. 说明 OS、Python 版本、`LLM_PROVIDER`、输入文件类型。  
3. 在 GitHub 提 Issue（开源后）。
