"""에이전트별 지시문(프롬프트)과 정해진 값들. 결과 형식을 바꾸고 싶으면 이 파일을 고친다.

맨 앞의 [ROLE:...] 표시는 테스트용 가짜 LLM(fake_llm.py)이 역할을 알아보는 데만 쓴다.
"""

# ── 작업 유형과, 그 유형을 알아보는 단어들 (LLM이 놓쳐도 코드가 한 번 더 확인) ──
WORK_TYPES = {
    "밀폐공간 작업": ["탱크", "맨홀", "반응기", "저장조", "밀폐", "피트", "정화조", "내부에 들어", "안에 들어"],
    "화기작업": ["용접", "절단", "그라인더", "화기", "토치", "불꽃", "납땜"],
    "고소작업": ["사다리", "비계", "고소", "지붕", "높은 곳", "랙", "2m", "3층", "리프트"],
    "화학물질 취급": ["옮겨 담", "소분", "드럼", "충전", "샘플링", "시료", "약품", "용제", "희석"],
}

# 위험도 = 가능성(1~3) × 심각도(1~3). 점수는 AI가 아니라 코드가 계산한다.
def risk_level(likelihood: int, severity: int) -> tuple[int, str]:
    likelihood = min(3, max(1, likelihood))   # AI가 범위 밖 숫자를 주면 1~3으로 맞춘다
    severity = min(3, max(1, severity))
    score = likelihood * severity
    if score >= 6:
        return score, "상"
    if score >= 3:
        return score, "중"
    return score, "하"


ANALYZE_SYSTEM = """[ROLE:ANALYZE]
너는 화학 공장의 작업 분석 담당이다. 작업 계획을 읽고 JSON 하나만 출력한다.

- is_work_plan: 공장/현장 작업 계획이면 true, 인사·잡담·무관한 질문이면 false
- summary: 작업 내용을 한 문장으로 요약
- location: 작업 장소 (모르면 "")
- work_types: 다음 중 해당하는 것 모두 → "밀폐공간 작업", "화기작업", "고소작업", "화학물질 취급"
- chemicals: 작업에 등장하는 화학물질의 영어 이름 목록 (예: 톨루엔 → "toluene"). 없으면 []
- workers: 작업 인원 수 (모르면 0)

출력 예시:
{"is_work_plan": true, "summary": "톨루엔 저장탱크 내부 용접 보수", "location": "T-201 저장탱크",
 "work_types": ["밀폐공간 작업", "화기작업"], "chemicals": ["toluene"], "workers": 2}"""

WRITER_SYSTEM = """[ROLE:WRITER]
너는 화학 공장의 작업 전 위험성평가(JSA) 작성 담당이다. [조사 결과]만 근거로 JSON 하나만 출력한다.

출력 형식:
{"rows": [
   {"step": "작업 단계", "hazard": "위험 요인", "likelihood": 1~3, "severity": 1~3,
    "controls": ["안전 대책1", "안전 대책2"], "basis": ["SAFE-04"]}
 ],
 "pre_checks": ["작업 시작 전에 확인할 것"],
 "ppe": ["필요한 보호구"]}

규칙:
1. rows는 작업 순서대로 3~6개 쓴다. 각 작업 유형의 위험이 적어도 하나씩 들어가야 한다.
2. likelihood(발생 가능성)와 severity(심각도)는 1(낮음)~3(높음) 정수로 쓴다.
3. controls에는 조사 결과에 있는 구체적인 대책(수치 포함)을 쓴다. 지어내지 않는다.
4. basis에는 근거가 된 사내 규정 번호(SAFE-xx)만 쓴다.
5. [관리자 반려 의견]이 있으면 반드시 반영한다."""


def writer_user_message(request: str, analysis: dict, context: str, feedback: str = "") -> str:
    msg = (f"[작업 계획]\n{request}\n\n"
           f"[작업 분석]\n요약: {analysis.get('summary')}\n"
           f"작업 유형: {', '.join(analysis.get('work_types', []))}\n"
           f"인원: {analysis.get('workers') or '미기재'}\n\n"
           f"[조사 결과]\n{context}")
    if feedback:
        msg += f"\n\n[관리자 반려 의견 — 반드시 반영]\n{feedback}"
    return msg
