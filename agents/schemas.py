"""구조화된 출력(Structured Output)의 '틀' — AI가 만든 JSON이 이 모양인지 Pydantic으로 검사한다.

AI 답을 그냥 글로 받으면 매번 모양이 달라 표로 그릴 수 없다. 그래서
"이런 칸들이 있는 JSON으로 답해"라고 시키고, 받은 JSON을 이 클래스에 넣어 검사한다.
"""
import json
import re

from pydantic import BaseModel


class WorkAnalysis(BaseModel):
    """작업 분석 에이전트의 결과"""
    is_work_plan: bool = True
    summary: str = ""
    location: str = ""
    work_types: list[str] = []
    chemicals: list[str] = []
    workers: int = 0


class JSARow(BaseModel):
    """위험성평가표 한 줄"""
    step: str = ""                  # 작업 단계
    hazard: str = ""                # 위험 요인
    likelihood: int = 2             # 발생 가능성 1~3
    severity: int = 2               # 심각도 1~3
    controls: list[str] = []        # 안전 대책
    basis: list[str] = []           # 근거 규정 번호
    score: int = 0                  # 위험 점수 (코드가 계산)
    level: str = ""                 # 상/중/하 (코드가 계산)


class JSADraft(BaseModel):
    """평가표 작성 에이전트의 결과"""
    rows: list[JSARow] = []
    pre_checks: list[str] = []      # 작업 전 확인사항
    ppe: list[str] = []             # 필요한 보호구


def parse_json_as(text: str, model: type[BaseModel]) -> BaseModel:
    """AI가 준 글에서 { ... } 부분만 꺼내 Pydantic 모델로 바꾼다. 실패하면 빈 모델."""
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return model.model_validate(json.loads(m.group(0)))
    except Exception:
        return model()
