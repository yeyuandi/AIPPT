# -*- coding: utf-8 -*-
"""
合并多个单页 PPTX 为一个文件（拷贝形状 XML 并重映射图片 rId，避免后续页丢媒体呈空白）。

仅合并、不截图的命令行入口请使用 **`python -m aippt.export.rerender_html_dir <dir> --merge-only`**（按 ``deck_outline.json`` 顺序）。
流水线与其它模块通过 **`merge_pptx_files`** / **`resolve_pptx_paths_from_deck_outline`** 编程调用。
"""
# 从 __future__ 导入注解
from __future__ import annotations

# 导入 json 读取 deck_outline.json
import json
# 从 copy 导入深拷贝用于复制 XML 元素树
from copy import deepcopy
# 导入 io 以便把图片二进制包装成类文件对象
import io
# 从 pathlib 导入路径类型
from pathlib import Path
# 从 typing 导入字典类型别名（旧 rId -> 新 rId）
from typing import Dict

# 从 pptx 导入演示文稿类（类型注解与打开文件均需）
from pptx import Presentation
# 从 pptx.parts.image 导入图片部件类型，用于 isinstance 校验
from pptx.parts.image import ImagePart

# OOXML 命名空间：关系中的 embed 属性（DrawingML blip 等引用图片时使用）
_NS_ODREL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
# lxml Clark 记法下的 embed 完整属性名（drawing 内嵌图片）
_Q_EMBED = "{%s}embed" % _NS_ODREL


def _pick_blank_layout(prs: Presentation):
    """
    为追加页挑选最接近「空白」的版式，避免硬编码 ``slide_layouts[6]`` 在某些模板不存在或语义不一致。

    @param prs - 作为合并主体的 Presentation（沿用其母版）
    @returns 选中的 SlideLayout
    """
    layouts = prs.slide_layouts  # 枚举当前演示文稿全部版式
    for layout in layouts:  # 优先按名称匹配 Blank（中英文模板常见）
        name = (layout.name or "").strip().lower()  # 规范化名称便于模糊匹配
        if "blank" in name:  # 名称中包含 blank 即视为空白版式候选
            return layout  # 命中后立即返回
    # 若无命名命中：退回最后一个版式（Office 内置模板里通常占位最少）
    return layouts[len(layouts) - 1]


def _remap_image_embeds(cloned_element, source_slide_part, dest_slide_part) -> None:
    """
    在深拷贝后的 XML 子树内扫描 ``a:blip`` 等节点的 ``r:embed``，把图片复制进目标包并改写为新 rId。

    @param cloned_element - 单个形状根元素或其 subtree（已与源文档断开）
    @param source_slide_part - 源幻灯片 part（用于 ``related_part(old_rid)``）
    @param dest_slide_part - 新幻灯片 part（调用 ``get_or_add_image_part`` 注册媒体）
    @returns None
    """
    rid_map: Dict[str, str] = {}  # 缓存同一幻灯片内重复使用同一图片时的 rId 映射

    for el in cloned_element.iter():  # 深度优先遍历拷贝树上的全部 XML 节点
        if _Q_EMBED not in el.attrib:  # 无嵌入关系属性则跳过（可能有 link 外链，暂不处理）
            continue
        old_rid = el.attrib.get(_Q_EMBED)  # 读出旧的 relationship id 字符串
        if not old_rid:  # 防空头
            continue
        if old_rid in rid_map:  # 若已为该旧 id 建立过新映射
            el.attrib[_Q_EMBED] = rid_map[old_rid]  # 直接复用新 rId，保持与同页其它引用一致
            continue
        try:
            related = source_slide_part.related_part(old_rid)  # 从源 slide 的关系表中解析目标 part
        except KeyError:
            continue  # 残缺或过旧的 rel 表：跳过该引用以免中断合并
        if not isinstance(related, ImagePart):  # 仅处理位图部件（图表/OLE 需另行迁移）
            continue
        _, new_rid = dest_slide_part.get_or_add_image_part(io.BytesIO(related.blob))  # 写入主包并建立 slide→image 关系
        rid_map[old_rid] = new_rid  # 记录映射供后续重复引用使用
        el.attrib[_Q_EMBED] = new_rid  # 就地改写 XML，保存后即指向目标包内新媒体文件


def merge_pptx_files(source_paths: list[Path], output_path: Path) -> None:
    """
    按顺序合并多个 pptx，幻灯片尺寸以第一份为准。

    @param source_paths - 非空 pptx 路径列表（顺序即播放顺序）
    @param output_path - 写出合并结果的绝对路径
    @returns None
    """
    if not source_paths:  # 若列表为空则立即报错避免无效 IO
        raise ValueError("source_paths 不能为空")  # 抛出显式业务异常

    master = Presentation(str(source_paths[0]))  # 打开第一份作为基底演示文稿对象
    base_w = master.slide_width  # 记录基准幻灯片宽度 EMU
    base_h = master.slide_height  # 记录基准幻灯片高度 EMU

    blank_layout = _pick_blank_layout(master)  # 解析基底文稿上的空白版式（取代固定索引 6）

    # 从第二份文件开始遍历追加幻灯片（第一份已全部保留）
    for path in source_paths[1:]:
        other = Presentation(str(path))  # 打开当前待合并的演示文稿
        if other.slide_width != base_w or other.slide_height != base_h:  # 若宽高不一致则打印告警（仍尝试合并）
            msg = f"警告：幻灯片尺寸不一致 {path.name}，可能与基底不完全对齐"  # 拼接告警文案
            print(msg, flush=True)  # 输出到标准输出提示用户审阅

        # 遍历该文件中的每一页幻灯片对象
        for slide in other.slides:
            new_slide = master.slides.add_slide(blank_layout)  # 在 master 上追加一页空白承载拷贝的形状
            dest_part = new_slide.part  # 新幻灯片 OPC part（注册图片关系的目标）
            src_part = slide.part  # 源幻灯片 part（解析旧 rId 的来源）

            # 逐个拷贝旧幻灯片中的形状元素 XML 节点到新幻灯片
            for shape in slide.shapes:
                el = shape.element  # 获取底层 lxml 元素引用
                clone = deepcopy(el)  # 深拷贝元素树避免与原幻灯片共享引用
                _remap_image_embeds(clone, src_part, dest_part)  # 关键：把图片 blob 迁入 master 包并重写 rId
                new_slide.shapes._spTree.append(clone)  # 追加到空白页形状树末尾（兼容无 p:extLst 的版式）

    output_path.parent.mkdir(parents=True, exist_ok=True)  # 确保输出目录存在（多级创建）
    master.save(str(output_path))  # 将内存中的演示文稿写出到磁盘路径


def resolve_pptx_paths_from_deck_outline(
    directory: Path,
    outline_path: Path,
    *,
    append_unlisted: bool,
    output_path: Path,
) -> list[Path]:
    """
    按 ``deck_outline.json`` 中 ``slides`` 顺序解析各页 ``pptx_file``，拼接为合并列表。

    @param directory - 单页 pptx 所在目录（``pptx_file`` 视为相对此目录）
    @param outline_path - ``deck_outline.json`` 路径
    @param append_unlisted - True 时在大纲列出的文件之后追加目录内其余 ``*.pptx``（按文件名排序，排除输出文件）
    @param output_path - 合并输出路径（解析后与同名文件不参与「追加未列出」）
    @returns 绝对路径列表（顺序即播放顺序）
    @raises FileNotFoundError - 大纲缺失或某大纲条目对应的 pptx 不存在
    @raises ValueError - JSON 结构非法或未能解析出任何 pptx
    """
    if not outline_path.is_file():
        msg = f"找不到大纲文件: {outline_path}"
        raise FileNotFoundError(msg)

    data = json.loads(outline_path.read_text(encoding="utf-8"))
    slides = data.get("slides")
    if not isinstance(slides, list):
        msg = "deck_outline.json 顶层须包含 slides 数组"
        raise ValueError(msg)

    root = directory.expanduser().resolve()
    ordered: list[Path] = []
    seen: set[Path] = set()

    for slide in slides:
        if not isinstance(slide, dict):
            continue
        name = str(slide.get("pptx_file") or "").strip()
        if not name:
            continue
        candidate = (root / name).resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)

    missing = [p for p in ordered if not p.is_file()]
    if missing:
        lines = "\n  ".join(str(p) for p in missing)
        msg = f"下列大纲中的 pptx 在磁盘上不存在:\n  {lines}"
        raise FileNotFoundError(msg)

    if not ordered:
        msg = "deck_outline.json 中没有任何有效的 pptx_file 条目"
        raise ValueError(msg)

    out_res = output_path.expanduser().resolve()
    listed = set(ordered)

    if not append_unlisted:
        return ordered

    extras: list[Path] = []
    for p in sorted(root.glob("*.pptx"), key=lambda x: str(x).lower()):
        r = p.resolve()
        if r == out_res or r in listed:
            continue
        extras.append(r)

    return ordered + extras
