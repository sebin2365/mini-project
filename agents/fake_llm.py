"""LLM_BACKEND=fake — 인터넷·Ollama 없이 전체 흐름을 시험해 보기 위한 '가짜 LLM'.

진짜 AI가 아니라 정해진 규칙대로 JSON을 만들어 준다. 화면·서버·그래프·도구 연결이
제대로 됐는지 빠르게 확인할 때만 쓴다. LangChain의 BaseChatModel을 상속해서 진짜 모델과
똑같이 ainvoke로 부를 수 있다 — 그래서 그래프 코드는 백엔드가 바뀌어도 그대로다.
"""
import json
import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agents.prompts import WORK_TYPES
from tools.pubchem import find_known_chemicals


def fake_analyze(text: str) -> dict:
    types = [t for t, words in WORK_TYPES.items() if any(w in text for w in words)]
    chems = find_known_chemicals(text)
    m = re.search(r"(\d+)\s*명", text)
    return {"is_work_plan": bool(types or chems), "summary": text[:40], "location": "",
            "work_types": types, "chemicals": chems, "workers": int(m.group(1)) if m else 0}


def fake_writer(text: str) -> dict:
    """조사 결과에 나온 규정마다 평가표 한 줄을 만든다."""
    rows = []
    for mid, title in re.findall(r"\[(SAFE-\d+) ([^\]]+)\]", text):
        if mid == "SAFE-01":
            continue
        rows.append({"step": title, "hazard": f"{title} 관련 위험",
                     "likelihood": 2, "severity": 3,
                     "controls": [f"{mid} 규정의 작업 전 절차 준수"], "basis": [mid]})
    if "[관리자 반려 의견" in text:
        comment = text.split("[관리자 반려 의견 — 반드시 반영]")[-1].strip()
        rows.append({"step": "관리자 의견 반영", "hazard": "추가 확인 필요", "likelihood": 1,
                     "severity": 2, "controls": [comment], "basis": []})
    return {"rows": rows, "pre_checks": ["(가짜 LLM) 작업허가서 발급 확인"],
            "ppe": ["안전모", "안전화"]}


class FakeChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fake-safework"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        system, user = str(messages[0].content), str(messages[-1].content)
        if "[ROLE:ANALYZE]" in system:
            answer = fake_analyze(user)
        else:
            answer = fake_writer(user)
        text = json.dumps(answer, ensure_ascii=False)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(text))])
