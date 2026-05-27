# aippt.search · DuckDuckGo 检索

基于 [duckduckgo-search](https://pypi.org/project/duckduckgo-search/)（`DDGS`）的联网检索封装，供流水线、脚本或 Agent 调用。

| 文件 | 说明 |
|------|------|
| `duckduckgo_tools.py` | 工具类、参数目录、CLI |
| `__init__.py` | 包导出（延迟导入） |

---

## 依赖安装

仓库根目录 `requirements.txt` 已包含：

```bash
pip install ddgs
```

**说明**：上游包已由 `duckduckgo-search` 更名为 [`ddgs`](https://pypi.org/project/ddgs/)。本模块 **优先** `import ddgs`；若未安装则回退 `duckduckgo_search`。

**运行要求**：

- 可访问外网（检索请求由 DuckDuckGo / 后端转发完成）
- 若遇限流或地区网络问题，需配置 **代理**（见下文）

---

## 命令行用法

模块入口：

```bash
python -m aippt.search.duckduckgo_tools [选项] MODE ...
```

### 查看全部参数说明

```bash
python -m aippt.search.duckduckgo_tools --list-params
```

输出与代码内 `DDGS_PARAMETER_CATALOG` 一致，涵盖 `DDGS.__init__`、`text`、`images`、`videos`、`news` 各方法参数。

### 文本检索（网页）

```bash
python -m aippt.search.duckduckgo_tools text \
  -k "大语言模型" \
  -n 5 \
  --region cn-zh \
  --safesearch moderate
```

常用选项：

| 选项 | 说明 |
|------|------|
| `-k` / `--keywords` | 检索词（必填） |
| `-n` / `--max-results` | 最大条数（默认 5） |
| `--region` | 区域，如 `cn-zh`、`us-en`、`wt-wt`（无区域） |
| `--safesearch` | `on` / `moderate` / `off` |
| `--timelimit` | `d` / `w` / `m` / `y` |
| `--backend` | `auto`、`html`、`lite`、`bing` 等 |
| `--proxy` | HTTP(S)/SOCKS 代理 |
| `--timeout` | 超时秒数（默认 10） |
| `--no-verify-ssl` | 关闭 SSL 校验 |

### 新闻检索

```bash
python -m aippt.search.duckduckgo_tools news \
  -k "人工智能" \
  -n 10 \
  --region cn-zh \
  --timelimit w
```

**说明**：`ddgs` 的 `news` 默认 `backend=auto` 会并行请求 **Yahoo** 等后端，在国内网络下 Yahoo 常超时，而 `text` 却能正常返回。本模块已做两点处理：

1. 默认 `--backend duckduckgo,bing`，顺序尝试，**不**走 Yahoo
2. 专用新闻后端仍无结果时，自动 **回退为 `text` 检索**（关键词追加「新闻」），并映射为 `title/url/body` 字段

若只要原生新闻 API、不要回退：

```bash
python -m aippt.search.duckduckgo_tools news -k "人工智能" --no-fallback-text --backend duckduckgo
```

### 图片检索

```bash
python -m aippt.search.duckduckgo_tools images \
  -k "商务 PPT 背景" \
  -n 8 \
  --region wt-wt
```

### 视频检索

```bash
python -m aippt.search.duckduckgo_tools videos \
  -k "Python 教程" \
  -n 5
```

成功时 stdout 为 **JSON 数组**；stderr 会打印「共 N 条」。

---

## Python API

### 便捷函数

```python
from aippt.search import search_text, search_news

rows = search_text("LangChain 教程", max_results=5, region="cn-zh")
for r in rows:
    print(r["title"], r["href"])

news = search_news("AI", max_results=10, timelimit="w")
```

同样可用：`search_images()`、`search_videos()`。

### 工具类（推荐：需代理或自定义客户端）

```python
from aippt.search import DuckDuckGoSearchTool, DuckDuckGoClientOptions

tool = DuckDuckGoSearchTool(
    DuckDuckGoClientOptions(
        proxy="http://127.0.0.1:7890",
        timeout=20,
        verify=True,
    )
)

results = tool.search_text(
    "site:github.com LangGraph",
    region="wt-wt",
    safesearch="off",
    max_results=10,
)
```

| 类 / 函数 | 作用 |
|-----------|------|
| `DuckDuckGoSearchTool` | 文本 / 图片 / 视频 / 新闻四类检索 |
| `DuckDuckGoClientOptions` | `proxy`、`timeout`、`verify`、`headers` |
| `format_parameter_catalog_text()` | 打印参数目录文本 |
| `DDGS_PARAMETER_CATALOG` | 参数目录数据结构 |

### 方法一览

| 方法 | 对应 DDGS | 典型返回字段 |
|------|-----------|--------------|
| `search_text()` | `.text()` | `title`, `href`, `body` |
| `search_images()` | `.images()` | `title`, `image`, `thumbnail`, `url` |
| `search_videos()` | `.videos()` | `title`, `content`, `embed_url`, `duration` |
| `search_news()` | `.news()` | `title`, `url`, `body`, `date` |

---

## 检索语法（关键词运算符）

与 DuckDuckGo 官方一致，可在 `-k` / `keywords` 中使用：

| 示例 | 含义 |
|------|------|
| `"精确短语"` | 精确匹配 |
| `cats -dogs` | 排除 dogs |
| `cats +dogs` | 强调 dogs |
| `报告 filetype:pdf` | 限定 PDF |
| `教程 site:github.com` | 限定站点 |
| `intitle:入门` | 标题含关键词 |

---

## 区域代码（region）

常用值：

| 代码 | 说明 |
|------|------|
| `cn-zh` | 中国 |
| `us-en` | 美国（英语） |
| `wt-wt` | 不指定区域 |

完整列表见 [duckduckgo-search 文档](https://github.com/deedy5/duckduckgo_search#regions) 或 `--list-params` 说明。

---

## 代理与环境变量

**命令行**：

```bash
python -m aippt.search.duckduckgo_tools text -k "test" --proxy "http://127.0.0.1:7890"
```

**代码**：

```python
DuckDuckGoClientOptions(proxy="socks5h://user:pass@host:port")
```

**环境变量**（duckduckgo-search 原生支持）：

```bash
set DDGS_PROXY=http://127.0.0.1:7890
```

Tor 浏览器别名：`proxy="tb"`（等价 `socks5://127.0.0.1:9150`）。

---

## 常见问题

### 1. `ImportError: duckduckgo_search`

```bash
pip install duckduckgo-search
# 或
pip install ddgs
```

### 2. `text` 正常但 `news` 超时（Yahoo）

典型日志含 `news.search.yahoo.com`。原因是 `ddgs` 新闻 `backend=auto` 会请求 Yahoo，而 text 走的是其它可用后端。

**处理**：直接使用本模块默认行为（已改为 `duckduckgo,bing` + text 回退），或显式指定：

```powershell
python -m aippt.search.duckduckgo_tools news -k "人工智能" -n 10 --region cn-zh
```

### 3. `TimeoutError` / `operation timed out`

典型日志：

```text
检索失败: ... operation timed out
可能原因：无法直连 DuckDuckGo / 检索后端（常见于未开代理或防火墙拦截）。
```

**处理**：

1. 开启可用的 HTTP(S) 代理（Clash、V2Ray 等），确认本地端口（常见 `7890`）
2. 设置环境变量或命令行参数：

```powershell
$env:DDGS_PROXY = "http://127.0.0.1:7890"
python -m aippt.search.duckduckgo_tools news -k "人工智能" -n 10
```

或：

```powershell
python -m aippt.search.duckduckgo_tools news -k "人工智能" --proxy http://127.0.0.1:7890 --timeout 30
```

### 3. `RuntimeWarning: renamed to ddgs`

表示仍在使用旧包 `duckduckgo-search`。执行 `pip install ddgs` 并确保已升级本仓库依赖即可消除。

### 4. 包重命名

安装 `duckduckgo-search` 时可能提示已更名为 `ddgs`；请改用 `pip install ddgs`。

### 5. 与 aippt 其它子包的关系

| 子包 | 职责 |
|------|------|
| `aippt/search/` | 联网检索（本模块） |
| `aippt/tts/` | 语音合成（edge-tts） |
| `aippt/media/` | 音视频处理（FFmpeg） |
| `aippt/export/` | HTML → PPTX 导出 |

检索结果可用于补充大纲素材、生成引用页等，需自行在业务层接入（Web 向导暂未内置本模块）。

---

## 上游参考

- PyPI：[duckduckgo-search](https://pypi.org/project/duckduckgo-search/)
- GitHub：[deedy5/duckduckgo_search](https://github.com/deedy5/duckduckgo_search)
