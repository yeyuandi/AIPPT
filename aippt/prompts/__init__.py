# -*- coding: utf-8 -*-
"""
LangChain 链路使用的提示词与嵌入 CSS 片段集中于此模块，便于统一维护。

构建模板时：嵌入 ``ChatPromptTemplate`` 的 CSS 须先经 ``escape_lc_prompt_braces`` 转义花括号。
"""

RASTER_SCREEN_LAYOUT_CSS = """\
请在首个 <style> 标签内**开头**包含下列基底样式（可在其后任意追加配色、字体与排版；勿删除下列关键约束）：
html{
  font-size:17px;
}
html,body{
  height:100%;
  margin:0;
  padding:0;
  overflow:hidden;
}
.slide{
  box-sizing:border-box;
  width:100%;
  height:100%;
  overflow:hidden;
  display:flex;
  flex-direction:column;
  min-height:0;
}
.slide > *:only-child{
  flex:1 1 auto;
  min-height:0;
  overflow:hidden;
}
"""

# ---------------------------------------------------------------------------
# 截图导出：每页 HTML 强制引入的 CDN（须与模型输出字面一致，供 Playwright 联网拉取）
# ---------------------------------------------------------------------------

RASTER_REQUIRED_EXTERNAL_RESOURCES_BLOCK = """\
【必需引入的资源】
<!-- Bootstrap 5 CSS -->
<link href="https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.8/css/bootstrap.min.css" rel="stylesheet">
<!-- Bootstrap Icons CSS -->
<link href="https://cdn.bootcdn.net/ajax/libs/bootstrap-icons/1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<!-- Bootstrap 5 JS Bundle -->
<script src="https://cdn.bootcdn.net/ajax/libs/twitter-bootstrap/5.3.8/js/bootstrap.bundle.min.js"></script>
"""

# ---------------------------------------------------------------------------
# 大纲链（JSON DeckOutline）
# ---------------------------------------------------------------------------

OUTLINE_SYSTEM_PROMPT = (
    "你是演示文稿策划助手。请先通读全文，理解结构与论点，再划分为若干页幻灯片。\n"
    "务必只输出一个 JSON 对象，不要 Markdown，不要解释。\n"
    "【页型顺序】请严格遵守用户消息中的「页数说明」：若允许至少 3 页，则 **`slides[0]` 封面**，**`slides[1]` 目录页**，**`slides[2]` 起为正文内容页**；"
    "若用户只允许 1～2 页，则不强行插入目录页（见用户消息）。\n"
    "重要：`slides[0]`（第一页）必须是**整套演示的封面/标题页**：`title` 为演示主标题；"
    "`summary` 宜作一行副标题或主题说明（可较短）；`bullets` 可为 0～2 条装饰性信息（如场合、日期关键词），不要写成正文要点列表。\n"
    "当存在 **`slides[1]` 目录页**时：`title` 建议为「目录」「议程」或简短自拟（≤18 字）；"
    "`summary` 为一句目录引导语（约 20～60 字），**不要**写成正文式的长叙事概要；"
    "`bullets` 为目录条目：**条数与顺序须与 `slides[2]` 及之后每一正文页的 `title` 一一对应**（第 k 条对应 `slides[k+1].title`，文字可相同或略缩短），"
    "每条 ≤40 字；**禁止**把目录页写成「多条论证要点」的正文版式。\n"
    "**正文内容页**（通常为 `slides[2]` 及以后；若无目录则从 `slides[1]` 起）：每项必须包含：\n"
    "  • `title`：该页标题，≤18 个汉字。\n"
    "  • `summary`：该页「要讲什么」的叙事概要，60～120 个汉字；须能在脱离原文情况下让读者明白本页主旨与上下文。\n"
    "  • `bullets`：3～5 条要点，每条 ≤40 个汉字，支撑 summary；**宜写成可单独排版的上屏短语或小句**，避免单条内塞进一整段长篇论证（以免 HTML 页挤爆）。\n"
    "页数约束：以用户消息中的「最多生成页数」与「页数软目标」（若有）或自行规划规则为准；slides 长度即为总页数。\n"
    "不得输出 slides 以外多余顶层字段。\n"
    "JSON 形状示例（注意仅为结构示意，含封面+目录+一页正文）："
    '{{"slides":[{{"title":"","summary":"","bullets":[]}},{{"title":"","summary":"","bullets":[]}},{{"title":"","summary":"","bullets":["",""]}}]}}。\n'
    "若原文过长：优先保留主线，弱化细节；页序符合叙事逻辑。\n"
)

OUTLINE_HUMAN_PROMPT = (
    "以下是需要转化的文档全文：\n\n{document}\n\n{max_slides_instruction}{target_slides_instruction}"
)

OUTLINE_SLIDES_UNLIMITED_INSTRUCTION = (
    "页数策略：用户未指定页数上限。请根据全文信息量自行确定幻灯片总页数（建议约 **4～16 页**，须包含封面、目录与正文；"
    "全文较短时也至少 **3 页**：封面 + 目录 + 至少一页正文）。\n"
    "输出 JSON 中 slides 数组的长度即为最终总页数。\n"
    "页型顺序固定：`slides[0]` 封面，`slides[1]` **目录**，`slides[2]` 起正文；目录条目 bullets 与正文各页 title 一一对应。\n"
)

# ---------------------------------------------------------------------------
# 单页 HTML 链 — human（正文素材段，嵌入截图导出链路）
# ---------------------------------------------------------------------------

HTML_SLIDE_HUMAN_PROMPT = (
    "本页标题：{title}\n\n"
    "本页内容概要（必须醒目呈现，可拆成 1～2 段）：\n{page_summary}\n\n"
    "要点列表（每行一条）：\n{bullets_lines}\n"
    "{style_hints_section}"
    "\n"
    "内容充实度：上述素材为本页可靠依据，请在**不曲解原意**前提下适度补充阐释、过渡句、听众收益或要点下的简短展开，"
    "使单页信息完整、版面分区均衡，避免出现大块无意义留白或「仅占半页」的稀疏排版。\n"
    "**版面密度**：同一 `.slide` 可视高度有限；**宁可删减措辞、合并次要句子**，也不得纵向堆砌「双栏长段落概要 + 多张卡片各含长段落」导致溢出裁切。"
    "概要段每条控制在听众**两三行内**读完为宜。\n"
    "（`.slide` 内勿出现与导出或前端相关的技术规格类可见文字，详见 system。）\n"
)

# ---------------------------------------------------------------------------
# 单页 HTML system（截图导出：基底布局 CSS + 视口说明）
# ---------------------------------------------------------------------------

RASTER_SCREEN_HTML_HEAD = (
    "你是前端设计师，输出单个完整 HTML 文件（一整页幻灯片）。下游将把本页 **``.slide`` 区域栅格截图**写入 PPTX（不包含 slide 外的页面留白）。\n"
    "**听众可见的画面上只呈现演示主题相关内容**（标题、正文、图表装饰等），不要把前端工程、导出流水线或屏幕规格写成给观众看的文字。\n"
    "截图模式下图层由浏览器渲染即可：**允许**使用外链 HTTPS CDN 的 CSS/JS、Bootstrap 工具类与组件、"
    "外链或内联 **SVG**、`<img src=\"https://...\">` 等；请确保导出时资源地址可公开访问（Playwright 需能下载）。\n\n"
)

def raster_viewport_alignment_segment(vw: int, vh: int) -> str:
    """
    raster_screen system 内的视口对齐说明。

    内含 ``html{{font-size}}`` 供 LangChain 转义为字面量 ``html{font-size}``；**禁止**对本段使用 ``str.format``，
    否则会先把 ``{{`` 折叠成 ``{``，导致 ChatPromptTemplate 将 ``{font-size}`` 误当作模板变量。

    @param vw - 导出视口 CSS 宽度（像素）；调用方传入以保持一致性，提示正文不宣读具体数值
    @param vh - 导出视口 CSS 高度（像素）；同上
    @returns 可直接拼入 system 提示的片段
    """
    del vw, vh
    return (
        "\n与导出视口对齐（必读）：下游在**固定浏览器视口**内渲染后，仅截取 **``.slide``** 边界框；若你用桌面浏览器预览，随意缩放窗口容易导致与导出稿不一致。\n"
        "因此：**禁止**主要用 `vw`/`vh` 控制字号、栏宽与关键间距；请在 `.slide` 内优先使用 **rem**（相对 `html{{font-size}}`）、"
        "**%**、`flex`/`grid` 以及必要时 **px**。\n"
        "**禁止**在听众可见区域写出具体像素、分辨率或画面比例等技术字样。\n\n"
    )


RASTER_SCREEN_HTML_TAIL = (
    "\n硬性约束（保持最少集合即可）：\n"
    '1) 根节点必须是 <div class="slide">...</div>，作为主内容容器。\n'
    "2) **单屏无滚动条**：不得出现纵向或横向滚动条；所有可见内容必须落在 **.slide 容器**内（可通过自适应字号、分栏、紧凑间距等方式）。\n"
    "2b) **防裁切**：`.slide` 可视高度固定、`overflow:hidden`。CSS Grid 行/列宜用 **`minmax(0, 1fr)`**；纵向需占据剩余空间的容器用 **`flex: 1 1 auto` + `min-height: 0`**。**禁止**对「概要区」「要点区」等**大块纵向分区**滥用 **`flex-shrink: 0`**（会把下方整块挤出可视区而被裁掉），除非该分区本身极矮。\n"
    "3) html、body：height:100%、margin:0、padding:0、overflow:hidden；**.slide：width:100%、height:100%**，铺满上述固定视口；"
    "勿对 body 使用 flex 居中缩小 .slide，勿使用 `min(100vw,…)` 把幻灯片变成小卡片；overflow:hidden。\n"
    "4) **必需引入的资源**：每一页输出的 HTML 均须**原样包含**下列片段（注释、标签与 URL 保持一致）；"
    "其中两条 `<link>` 放在 `<head>` 内（建议位于 `<meta charset>` / `<title>` 之后），"
    "`bootstrap.bundle.min.js` 的 `<script>` 放在 `</body>` 闭合标签之前：\n"
    + RASTER_REQUIRED_EXTERNAL_RESOURCES_BLOCK
    + "\n"
    "5) 其它资源：可额外引入其它 HTTPS CDN 样式表或脚本、外链图片等；图标可使用 **Bootstrap Icons**、emoji 或 SVG。\n"
    "6) **画面纯净（听众可见区）**：`<div class=\"slide\">` 内以及幻灯片上任何**可见**位置，**禁止**出现与演示主题无关的文案或标签，包括但不限于："
    "视口/画布/分辨率/像素数的直白展示、画面比例或安全区等技术规格说明、「导出」「截图」「栅格」「HTML」「Bootstrap」「CDN」「Playwright」「PPTX」「bootcdn」等工程或调试用语；"
    "禁止页脚角落的技术水印、设计规格、生成提示。**不要把 `<meta>`/`<link>`/`<script>` 的标签名或 URL 当正文展示。**\n"
    "    可在 `<style>` 外使用 `<!-- HTML 注释 -->` 供自检，但注释不得泄露到 `.slide` 子节点成为可见文本。\n"
    "    `<title>` 限与本页主题相关的简短文案（可与页眉标题一致），**禁止**写入尺寸或流水线说明。\n"
    "    **禁止**把对话中的区块标题当作页面正文输出（例如「封面文案素材」「本页正文素材」「BEGIN deck_template」「正文页标题对照」等字样不得出现在 `.slide` 内）。\n"
    "7) 只输出 HTML，不要 Markdown 围栏，不要解释。\n\n"
    "除此以外版式与视觉可自由发挥：可善用 Bootstrap 栅格与工具类；无矢量导出时代的「中文必须逐字包 span」等限制；"
    "仍以层次清晰、标题与概要醒目为佳。\n"
)

# ---------------------------------------------------------------------------
# slide_to_html_prompt_vars：概要为空时的兜底指令（写入 human 变量）
# ---------------------------------------------------------------------------

PAGE_SUMMARY_EMPTY_FALLBACK = (
    "（概要字段为空：请结合下列要点自拟 2～4 行引言，概括本页主旨与听众收益，"
    "放在标题下方单独区域，语气简洁有力。）"
)

# ---------------------------------------------------------------------------
# 整套 deck 的 HTML 模板页（raster_screen：先于各单页生成，落盘 deck_template.html）
# ---------------------------------------------------------------------------

RASTER_DECK_TEMPLATE_SYSTEM_SUFFIX = (
    "\n【任务类型】生成整套演示的 **HTML 模板参考文件**（将保存为 deck_template.html），供后续每一页幻灯片复用同一套视觉体系。\n"
    "输出要求：\n"
    "1) 输出**单个完整 HTML5 文档**；根节点仍须包含唯一主容器 `<div class=\"slide\">`（本文件内可作极简占位内容，但须保留该类名以便对齐截图流水线）。\n"
    "2) 在首个 `<style>` 标签内定义：**`:root` CSS 变量**（背景、主色、辅色、正文色、弱化色等）、**字体栈**、**基础字号阶梯**（如 h1/h2/正文）。\n"
    "3) 用注释或简短示例区分版式意图（不必生成真实多页）：`**封面**`、`**目录页**` 与 `**正文页**` 可共用 `:root` 变量；"
    "注释中说明封面居中、目录为条目列表区、正文为标题+概要+要点分区。\n"
    "4) `.slide` 须满足与下游一致的尺寸约束（width/height 100%、overflow:hidden），勿写依赖视口滚动的布局。\n"
    "5) **必需引入的资源**：与上文 system 要求一致，本模板须在 `<head>` / `</body>` 前**原样包含** Bootstrap 5 CSS、Bootstrap Icons、Bootstrap JS（bootcdn URL 不变）。\n"
    "    **说明**：后续生成的各单页 HTML **不得**把本模板文件里的 `<style>...</style>`、或对 `.slide`/`html`/`body` 的尺寸规则粘贴进输出；"
    "各页仅包含 system 规定的**基底布局**（见 raster 单页 system）、**自行写入**的 Bootstrap 三段引用，以及**必要时极少量的本页私有 `<style>`**。\n"
    "    本模板仅供模型阅读以统一配色与字体气质。\n"
    "6) 可选用其它外链 CSS/JS、图片或 SVG（截图时需网络可达）；图标可用 Bootstrap Icons。\n"
    "7) **画面纯净**：模板内若含占位正文，亦须遵守 raster 单页 common 规则——**不得**出现分辨率等技术规格、导出/截图/bootstrap 等可见说明文字。\n"
    "8) 只输出 HTML，不要 Markdown 围栏，不要解释。\n"
)

RASTER_DECK_TEMPLATE_HUMAN_PROMPT = (
    "下列为整套演示的**大纲标题列表**（顺序即播放顺序；第 1 条为封面，第 2 条为目录页标题，其后为各正文页）：\n"
    "{deck_outline_compact}\n\n"
    "下列为原文摘录（仅供提炼视觉气质、行业属性与配色方向；**禁止**把摘录整段贴进模板正文）：\n"
    "{document_excerpt}\n"
    "{style_hints_section}"
)

# ---------------------------------------------------------------------------
# 封面/标题页（raster_screen）：deck_template 仅供气质参考，禁止嵌入模板 CSS/尺寸
# ---------------------------------------------------------------------------

RASTER_TITLE_SLIDE_SYSTEM_EXTRA = (
    "\n【本页类型】**封面 / 标题页**：主标题显著居中（或清晰层级），可有副标题一条；"
    "可有极少行元信息（日期、场合、关键词）；**禁止**使用正文内容页的「概要长段 + 多条要点列表」版式。\n"
    "【与模板的关系】deck_template.html **仅供配色与气质参考**；输出中 **不得** 嵌入或拷贝其中的 `<style>...</style>` 及对 `.slide`/`html`/`body` 的尺寸定义。\n"
)

RASTER_TITLE_SLIDE_HUMAN_PROMPT = (
    "下列 **deck_template.html** 片段仅供理解整套演示的配色、字体与装饰气质（**勿当作可粘贴的样式源码**）。\n"
    "**禁止**将片段中的 `<style>...</style>` **整体或大部拷贝**到你输出的 HTML；"
    "**禁止**沿用模板中对 `.slide`、`html`、`body` 的宽高或定位定义（与 **system** 中的基底布局不一致时以 system 为准）。\n"
    "你可参照模板里的色值、字体族名等，在**本页新建的简短 `<style>`** 中手写需要的规则，或优先用 Bootstrap 工具类上色。\n"
    "**必需引入的资源**（Bootstrap CSS / Icons / JS）须在本页 HTML **按 system 要求自行原样写入**，不得依赖从模板复制 link/script。\n\n"
    "===== BEGIN deck_template.html（只读参考，勿粘贴 style） =====\n"
    "{deck_template_html}\n"
    "===== END deck_template.html =====\n\n"
    "--- 封面文案素材 ---\n"
    "主标题：{main_title}\n"
    "副标题（可为空，若空请自拟简短一行）：\n{subtitle}\n\n"
    "可选装饰信息（0～3 行；若无实质内容可省略区块）：\n{taglines_block}\n"
    "{style_hints_section}"
)

# ---------------------------------------------------------------------------
# 正文内容页（raster_screen）：human 附模板片段供气质参考，禁止嵌入模板样式
# ---------------------------------------------------------------------------

RASTER_CONTENT_SLIDE_SYSTEM_EXTRA = (
    "\n【本页类型】**正文内容页**：须有清晰的标题区、概要区与要点区（或等价信息分区），信息结构优于封面。\n"
    "【正文防超载（必读）】最易溢出裁切的版式是：**页眉 +「双栏长段落概要」+「下方 2×2（或更多）卡片且每卡再起一整段」**同时写满。"
    "请勿组合多种「大块分区」纵向满载；请选择其一为主的**稀疏**策略："
    "**要么**「短概要（每条≤约2行）+ 条目化列表」为主，**要么**「≤4 张卡片 + 每卡阐述≤约55～70字」为主。\n"
    "若必须「概要分区 + 要点分区」上下串联：概要每卡正文宜≤约 **90～100字**，要点每卡≤约 **55～65字**；**显性要点卡片不要超过 4 张**，其余要点可并入列表或合并叙述。"
    "减小 `.slide` 内边距与分区间距（padding/gap），标题字号勿过大。\n"
    "【与模板的关系】用户消息中的 deck_template.html **仅供配色与版式气质参考**；输出中 **不得** 嵌入或拷贝其中的 `<style>...</style>` 及对幻灯片尺寸的定义。\n"
)

RASTER_CONTENT_SLIDE_HUMAN_PROMPT = (
    "下列 **deck_template.html** 仅供阅读（色板、字体、装饰意图）；**禁止**将其 `<style>...</style>` 或模板里的尺寸规则粘贴进输出。\n"
    "本页样式来源仅限于：**system** 中的基底布局说明、**按 system 自行写入的 Bootstrap**、以及 **本页单独编写**的少量补充 CSS。\n"
    "（`<link>` 放在 `<head>`，`bootstrap.bundle` 的 `<script>` 放在 `</body>` 前。）\n\n"
    "===== BEGIN deck_template.html（只读参考，勿粘贴 style） =====\n"
    "{deck_template_html}\n"
    "===== END deck_template.html =====\n\n"
    "--- 本页正文素材 ---\n"
    + HTML_SLIDE_HUMAN_PROMPT
)

# ---------------------------------------------------------------------------
# 目录页（raster_screen）：版式区别于封面与正文；禁止嵌入 deck_template 的 style
# ---------------------------------------------------------------------------

RASTER_TOC_SLIDE_SYSTEM_EXTRA = (
    "\n【本页类型】**目录页 / 议程页**：仅用于展示后续章节的**导航结构**（编号列表、双栏条目、时间轴式纲要、带序号的卡片条等均可）；"
    "可读性与层级清晰优先。\n"
    "**禁止**使用封面式的「巨型主标题居中」作为主视觉；**禁止**使用正文内容页的「长段概要 + 多条论证要点」布局。\n"
    "【与模板的关系】deck_template.html **仅供气质参考**；**禁止**拷贝其中的 `<style>...</style>` 或模板中的幻灯片尺寸定义。\n"
    "可善用 Bootstrap 的 **list-group**、**row/col**、图标（bi-*）等排版目录条目。\n"
)

RASTER_TOC_SLIDE_HUMAN_PROMPT = (
    "下列 **deck_template.html** 仅供阅读；**禁止**将其 `<style>...</style>` 或尺寸规则粘贴进本页输出。\n"
    "样式须遵循 **system** 基底布局 + **自行写入**的 Bootstrap 三段引用 + **本页少量私有 `<style>`**（如需）。\n\n"
    "===== BEGIN deck_template.html（只读参考，勿粘贴 style） =====\n"
    "{deck_template_html}\n"
    "===== END deck_template.html =====\n\n"
    "--- 目录文案素材 ---\n"
    "本页主标题：{toc_page_title}\n\n"
    "引导语（较短，置于标题下）：\n{toc_intro}\n\n"
    "目录条目（每行一条；须覆盖并呼应下列正文标题，顺序一致）：\n{toc_entries_lines}\n\n"
    "【正文页标题对照】（目录条目应与之对应，文字可略缩短）：\n{content_headings_reference}\n"
    "{style_hints_section}"
)

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def escape_lc_prompt_braces(fragment: str) -> str:
    """
    将字符串中的 ``{`` ``}`` 加倍，供 LangChain ``ChatPromptTemplate`` 当作字面量。

    @param fragment - 原始片段（如 CSS）
    @returns 转义后的片段
    """
    return fragment.replace("{", "{{").replace("}", "}}")


def format_outline_max_slides_instruction(max_slides: int | None) -> str:
    """
    生成大纲链 ``human`` 消息中的页数说明段落。

    @param max_slides - 非 None 时不得超过该页数；None 表示由模型根据全文自行规划页数
    @returns 可直接填入 ``{{max_slides_instruction}}`` 的文本
    """
    if max_slides is None:
        return OUTLINE_SLIDES_UNLIMITED_INSTRUCTION
    base = f"最多生成页数（整数）：{max_slides}\n"
    if max_slides >= 3:
        return (
            base
            + "页型约束：须输出 **封面（slides[0]）**、**目录页（slides[1]）** 与 **至少一页正文（slides[2] 起）**。\n"
            + "目录页 `bullets` 须与 `slides[2]` 及之后各正文页的 `title` **顺序与条数一致**（逐条对应）。\n"
        )
    if max_slides == 2:
        return (
            base
            + "当前上限为 2：**无单独目录页**；`slides[0]` 为封面，`slides[1]` 为第一页正文。\n"
        )
    return base + "当前上限为 1：**仅输出封面** `slides[0]`。\n"


def validate_outline_slides_cli(max_slides: int | None, target_slides: int | None) -> str | None:
    """
    校验 ``--max-slides`` / ``--target-slides`` 参数组合。

    @param max_slides - CLI ``--max-slides``；None 表示未指定
    @param target_slides - CLI ``--target-slides``；None 表示未指定
    @returns 错误提示文案；None 表示通过
    """
    if target_slides is None:
        return None
    if target_slides < 1:
        return "--target-slides 须为 ≥1 的整数"
    if max_slides is not None and target_slides > max_slides:
        return "--target-slides 不得大于 --max-slides（软目标须在硬上限之内）"
    return None


def format_outline_target_slides_instruction(
    target_slides: int | None,
    *,
    max_slides: int | None,
) -> str:
    """
    生成大纲链 human 消息中的「页数软目标」段落（可为空串）。

    @param target_slides - 用户期望的大约总页数；None 表示不注入软目标
    @param max_slides - 与 ``--max-slides`` 一致，用于文案中呼应硬上限（可为 None）
    @returns 可直接填入 ``{{target_slides_instruction}}`` 的文本
    """
    if target_slides is None:
        return ""
    t = int(target_slides)
    if max_slides is not None:
        cap_line = (
            f"【页数软目标】在**不得超过**上文「最多生成页数」（{int(max_slides)}）的前提下，"
            f"请尽量将 ``slides`` 数组总长度规划为 **约 {t} 页**。\n"
        )
    else:
        cap_line = (
            f"【页数软目标】请尽量将 ``slides`` 数组总长度规划为 **约 {t} 页**（仍须符合全文信息量与叙事逻辑）。\n"
        )
    detail = (
        "可通过拆分章节、将并列论点拆成多页等方式接近该规模；若原文确实不足以支撑该页数，允许略少，"
        "但避免用过少的页数把过多内容挤在同一页。\n"
    )
    return cap_line + detail


def format_html_style_hints_section(html_style: str) -> str:
    """
    将用户给出的配色/风格描述格式化为 HTML 链路的 ``style_hints_section``。

    @param html_style - 用户自然语言偏好（可为空）
    @returns 空串表示无额外偏好；否则带标题的补充段落（截图导出：可自由配色，仍须单屏无滚动条）
    """
    text = (html_style or "").strip()
    if not text:
        return ""
    hint = "（当前为「``.slide`` 区域」栅格截图导出：可自由配色与装饰，仍须单屏、无滚动条。）\n"
    return f"\n【额外配色与风格偏好】\n{text}\n{hint}"


def build_raster_screen_html_system_prompt(layout_block_escaped: str, vw: int, vh: int) -> str:
    """
    组装 raster_screen 单页 HTML 的 system 提示（含已转义的布局 CSS 与视口说明）。

    @param layout_block_escaped - ``escape_lc_prompt_braces(RASTER_SCREEN_LAYOUT_CSS)``
    @param vw - 导出视口 CSS 宽度（像素）；供链路签名与未来扩展，提示词正文不宣读
    @param vh - 导出视口 CSS 高度（像素）；同上
    @returns 完整 system 字符串
    """
    return (
        RASTER_SCREEN_HTML_HEAD
        + layout_block_escaped
        + raster_viewport_alignment_segment(vw, vh)
        + RASTER_SCREEN_HTML_TAIL
    )


def build_raster_deck_template_system_prompt(layout_block_escaped: str, vw: int, vh: int) -> str:
    """
    raster_screen：生成 deck_template.html 的 system 提示（基础栅格约束 + 模板任务说明）。

    @param layout_block_escaped - 已转义的 ``RASTER_SCREEN_LAYOUT_CSS``
    @param vw - 视口宽
    @param vh - 视口高
    @returns 完整 system 字符串
    """
    return build_raster_screen_html_system_prompt(layout_block_escaped, vw, vh) + RASTER_DECK_TEMPLATE_SYSTEM_SUFFIX


def build_raster_title_slide_system_prompt(layout_block_escaped: str, vw: int, vh: int) -> str:
    """
    raster_screen：封面单页的 system（基础约束 + 封面版式说明）。

    @param layout_block_escaped - 已转义的布局 CSS 片段
    @param vw - 视口宽
    @param vh - 视口高
    @returns 完整 system 字符串
    """
    return build_raster_screen_html_system_prompt(layout_block_escaped, vw, vh) + RASTER_TITLE_SLIDE_SYSTEM_EXTRA


def build_raster_content_slide_system_prompt(layout_block_escaped: str, vw: int, vh: int) -> str:
    """
    raster_screen：正文单页的 system（基础约束 + 正文与模板一致性说明）。

    @param layout_block_escaped - 已转义的布局 CSS 片段
    @param vw - 视口宽
    @param vh - 视口高
    @returns 完整 system 字符串
    """
    return build_raster_screen_html_system_prompt(layout_block_escaped, vw, vh) + RASTER_CONTENT_SLIDE_SYSTEM_EXTRA


def build_raster_toc_slide_system_prompt(layout_block_escaped: str, vw: int, vh: int) -> str:
    """
    raster_screen：目录单页的 system（基础约束 + 目录版式与模板一致性说明）。

    @param layout_block_escaped - 已转义的布局 CSS 片段
    @param vw - 视口宽
    @param vh - 视口高
    @returns 完整 system 字符串
    """
    return build_raster_screen_html_system_prompt(layout_block_escaped, vw, vh) + RASTER_TOC_SLIDE_SYSTEM_EXTRA
