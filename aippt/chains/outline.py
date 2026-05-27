# -*- coding: utf-8 -*-
"""大纲抽取 LCEL 链路。"""
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from aippt.domain.models import DeckOutline
from aippt.parsers import parse_outline_json
from aippt.prompts import OUTLINE_HUMAN_PROMPT, OUTLINE_SYSTEM_PROMPT


def build_outline_chain(llm: Any):
    """
    构建「文档 → DeckOutline」链路。

    @param llm - 聊天模型（建议 json_mode=True）
    @returns 可 invoke 的 Runnable
    """
    tpl = ChatPromptTemplate.from_messages(
        [("system", OUTLINE_SYSTEM_PROMPT), ("human", OUTLINE_HUMAN_PROMPT)]
    )
    chain_raw = tpl | llm
    return chain_raw | RunnableLambda(lambda msg: parse_outline_json(msg.content))
