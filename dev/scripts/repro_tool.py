# -*- coding: utf-8 -*-
"""容器内复现：LangChain ChatOpenAI.bind_tools -> Ollama 是否产生 tool_calls"""
import sys
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool


@tool
def search_knowledge_base(query: str) -> str:
    """搜索产品知识库获取技术文档，设备参数、报错、校准问题必须调用。"""
    return "（工具结果）T100 测温范围 -20℃ ~ 550℃"


llm = ChatOpenAI(
    model="qwen2.5:7b",
    api_key="ollama",
    base_url="http://ollama:11434/v1",
    temperature=0.0,
)
llm_t = llm.bind_tools([search_knowledge_base])

msg = "T100 测温范围是多少？"
r = llm_t.invoke(msg)
sys.stderr.write("content=%r\n" % (r.content or "")[:200])
sys.stderr.write("tool_calls=%r\n" % getattr(r, "tool_calls", None))
