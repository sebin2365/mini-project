"""LLM 고르기 — 환경변수 LLM_BACKEND 하나로 fake / ollama / openai를 바꿔 끼운다.

LangChain의 Chat Model은 공급자(Ollama, OpenAI…)가 달라도 사용법(ainvoke)이
똑같다. 그래서 graph.py는 어떤 LLM이 꽂혀 있는지 몰라도 된다.

역할별로 모델을 나눈다.
  - analyzer : 작업 분석용. 빠르고 작은 모델
  - writer   : 위험성평가표 작성용. 더 똑똑한 모델
"""
import os


def backend_name() -> str:
    return os.environ.get("LLM_BACKEND", "ollama").lower()


def model_names() -> dict:
    b = backend_name()
    if b == "openai":
        return {"analyzer": os.environ.get("OPENAI_ANALYZER_MODEL", "gpt-4o-mini"),
                "writer": os.environ.get("OPENAI_WRITER_MODEL", "gpt-4o-mini")}
    if b == "ollama":
        return {"analyzer": os.environ.get("OLLAMA_ANALYZER_MODEL", "qwen3:0.6b"),
                "writer": os.environ.get("OLLAMA_WRITER_MODEL", "qwen3:8b")}
    return {"analyzer": "fake", "writer": "fake"}


def get_llm(role: str):
    """role = "analyzer" 또는 "writer"."""
    b = backend_name()
    name = model_names()[role]

    if b == "ollama":
        from langchain_ollama import ChatOllama
        # reasoning=False: qwen3의 <think> 생각 과정은 빼고 답만 받는다
        return ChatOllama(model=name, temperature=0, reasoning=False, format="json")
    if b == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=name, temperature=0)

    from agents.fake_llm import FakeChatModel
    return FakeChatModel()
